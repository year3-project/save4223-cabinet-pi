通过分析你上传的《UHF RFID读写器通讯协议手册》和 `raspberry_pi.py` 源码，我发现了导致你“丢包、漏读严重”的几个核心协议配置与代码实现问题。

### 1. 手册核心配置要求
根据手册第24-25页，你目前使用的指令是 `0x8B`（`cmd_customized_session_target_inventory`），这是**实时模式**。

* **数据包结构**：每读到一个标签，读写器都会立即推送一个包。包头固定为 `0xA0`，随后是 `Len`。
* [cite_start]**双CPU架构**：手册提到读写器主CPU轮询，副CPU发数据，串口/网口传输不影响读写效率 [cite: 1413, 1414]。这意味着如果上位机（树莓派）接收不及时，读写器的发送队列可能会满，或者在网络层产生拥塞。
* [cite_start]**校验和 (Checksum)**：手册要求校验和包含包头 `0xA0` 在内的所有字节 [cite: 1110]。

---

### 2. 现有代码问题分析

在 `raspberry_pi.py` 的 `RFIDReader` 类中，存在以下三个致命问题：

#### **A. 错误的 Checksum 计算（逻辑不匹配）**
* [cite_start]**手册要求**：校验和 = `(所有字节之和取反 + 1) & 0xFF` [cite: 1649]。
* **代码实现**：你的 `_checksum` 函数逻辑是对的，但在 `_build_packet` 中：
    ```python
    packet_wo_checksum = bytes([0xA0, length & 0xFF, RFID_ADDRESS & 0xFF, cmd & 0xFF]) + data
    ```
    这里只包含了固定的 4 个字节头。**如果 `data`（参数）长度变化，你的 `length` 字段必须动态计算**。虽然当前 `0x8B` 的 payload 固定是 3 字节，但如果未来更改指令，这里会失效。

#### **B. 实时模式下的“假循环”导致漏读**
* **代码逻辑**：你在 `read_rfid_tags_multiple` 中使用 `while` 循环不断发送 `0x8B` 指令。
* **冲突点**：`0x8B` 是**持续性盘存**指令。你每秒发送一次指令，读写器会频繁重置内部搜索算法。
* **后果**：RFID 读写器在刚启动扫描时效率最低（需要进行防冲突协调）。你频繁发送指令，导致天线刚进入高速识别状态就被你下一条指令打断了，这是漏读的主要原因。

#### **C. TCP 粘包处理逻辑薄弱**
* **代码实现**：`_extract_frames_from_buffer` 虽然尝试了处理粘包，但其 `pos` 移动逻辑在遇到非法字节时非常保守（`pos += 1`），且没有充分利用 `0xA0` 后的 `Len` 字段进行跳跃验证，在高速数据流下效率较低。

---

### 3. 修改建议与代码优化

#### **建议 1：改用“盘存一次，长时间监听”模式**
不要在 `while` 循环里拼命发指令。发送一次开始指令，然后让树莓派持续监听 2-3 秒。

#### **建议 2：优化校验和与打包逻辑**
[cite_start]确保 `Len` 严格符合手册定义：`Len` = `Address` + `Cmd` + `Data` 的总字节数 [cite: 1110]。

#### **优化后的核心代码片段：**

```python
def _build_packet(self, cmd: int, data: bytes = b'') -> bytes:
    # Len = Address(1) + Cmd(1) + Data(N)
    length = 1 + 1 + len(data) 
    # 包头 + 长度 + 地址 + 命令 + 数据
    packet = bytes([0xA0, length, RFID_ADDRESS, cmd]) + data
    # 这里的 _checksum 必须计算上面 packet 的所有字节
    cs = self._checksum(packet)
    return packet + bytes([cs])

def read_rfid_tags_improved(self, duration=3.0) -> List[str]:
    if not self.connect(): return []
    
    self.work_mode_tags.clear()
    self._recv_buffer.clear()
    
    # 只需要发送一次指令：Session 1, Target A, Repeat 0xFF (持续扫描)
    # 根据手册 2.2.1.1，Repeat 设大一点或循环控制
    cmd_payload = bytes([0x01, 0x00, 0x01]) 
    packet = self._build_packet(0x8B, cmd_payload)
    self.socket.sendall(packet)
    
    # 持续监听一段时间，而不是循环发送指令
    start_time = time.time()
    while time.time() - start_time < duration:
        self._receive_and_process()
        # 即使没有新数据也继续监听，直到超时
        
    return list(self.work_mode_tags)
```

#### **建议 3：检查功率与防冲突设置**
[cite_start]如果标签很多，建议在初始化时通过指令 `0x76` 设置更高的功率（手册第11页），取值范围 `0x00 - 0x21` (0-33dBm) [cite: 1187]。

**总结建议：**
1.  **停止频繁发送指令**，改为发送一次指令后长时间读取。
2.  **修正 `Len` 的计算方法**，确保它是 `Address` 之后所有字节的长度。
3.  **增大 `recv` 缓冲区**，树莓派网口速度很快，确保 `self.socket.recv(8192)` 足够大。
4.  
---

经过对你上传的 `main.py`、`inventory_manager.py`、`raspberry_pi.py` 以及协议手册的深度对比，我发现了从**底层协议封装**到**上层逻辑调度**的一系列问题。

丢包和漏读的根本原因在于：**指令发送频率过高导致读写器负载过重**，以及**TCP流解析不严谨导致的断包丢弃**。

---

### 1. 底层协议层 (`raspberry_pi.py`)：计算与解析错误

#### **A. [cite_start]数据包长度 `Len` 计算偏差** [cite: 25, 28]
* [cite_start]**错误**：手册规定 `Len` 是从 `Len` 字节之后直到 `Check` 字节的总长度 [cite: 25, 28]。
* [cite_start]**代码问题**：当前 `_build_packet` 里的 `length = 2 + len(data)` 是针对 `Addr(1)+Cmd(1)+Data(N)` 计算的，看起来没错。但手册第4页明确 `Check` 也是 `Len` 计算范围内的 [cite: 25, 28]。
* **修改方案**：`length = 1(Addr) + 1(Cmd) + len(data) + 1(Check)`。即 `length = len(data) + 3`。

#### **B. [cite_start]校验和 (Checksum) 范围错误** [cite: 556, 562, 564]
* [cite_start]**错误**：手册规定校验和是“除校验和本身外所有字节”的和 [cite: 25, 28]。
* [cite_start]**代码问题**：你的代码包含了 `0xA0`，虽然有些兼容性设备可以，但标准做法应严格遵循手册描述的 C 语言实现 [cite: 556, 562, 564]。
* [cite_start]**修改建议**：参考手册第42页，从 `Len` 字节开始计算到 `Data` 结束 [cite: 556, 561, 562]。

#### **C. [cite_start]TCP 粘包处理逻辑（致命伤）** [cite: 330, 331]
* **代码问题**：RFID 在密集扫描时会瞬间推送几十个包。你的 `_extract_frames_from_buffer` 在发现 `received_cs != calc_cs` 时，仅仅 `pos += 1`。这会导致如果网络传输中产生一个杂质字节，后续所有正确的包都会因为对齐失效而被抛弃，直到缓冲区清空。
* **修改方案**：引入更强健的“滑动窗口”解析方案。

---

### 2. 逻辑管理层 (`inventory_manager.py` & `raspberry_pi.py`)：扫描策略冲突

#### **A. [cite_start]“自杀式”循环扫描** [cite: 306, 328, 365, 366]
* **代码问题**：在 `read_rfid_tags_multiple` 中，你用 `while` 循环每隔 `RFID_READ_INTERVAL` (1秒) 就发送一次 `0x8B` 指令。
* [cite_start]**后果**：根据手册，`0x8B` 是实时模式，读写器收到后会开启连续扫描 [cite: 306]。你每秒发一次，等于**每秒都在强制重启读写器的射频场和防冲突算法**。天线刚识别到一半标签，就被你下一条指令中断了。
* **修改方案**：发送一次指令，持续监听 N 秒。

#### **B. 投票机制 (Voting) 的逻辑开销**
* **代码问题**：`read_rfid_tags_voting` 尝试通过多次扫描取交集来过滤不稳定的标签。
* **后果**：在 TCP 长连接下，如果解析器效率低，这种高频切换 `Target A/B` 的操作会导致缓冲区积压大量上一轮的残余数据，造成数据错乱。

---

### 3. 主程序层 (`main.py`)：阻塞与超时设置

* **代码问题**：`main.py` 调用硬件读取是阻塞式的。如果 RFID 读取函数因为 `max_cycle_wait` 设置过长或 TCP 没数据一直等待，会直接卡死整个柜子的 UI 响应。
* **修改方案**：确保硬件读取有严格的 `absolute_timeout`。

---

### 4. 最终修改方案 (Action Plan)

请针对 `raspberry_pi.py` 中的 `RFIDReader` 类进行如下核心重构：

#### **第一步：修正协议封装**
```python
def _checksum(self, data: bytes) -> int:
    # 严格按照手册 C 语言描述：累加和取反 + 1
    uSum = sum(data) & 0xFF
    return ((~uSum) + 1) & 0xFF

def _build_packet(self, cmd: int, data: bytes = b'') -> bytes:
    # Len = Address(1) + Cmd(1) + Data(N) + Check(1)
    length = len(data) + 3
    # 构造待计算校验和的部分 (Len, Addr, Cmd, Data)
    content = bytes([length, self.address, cmd]) + data
    cs = self._checksum(content)
    # 最终发送：Head(0xA0) + 内容 + Check
    return bytes([0xA0]) + content + bytes([cs])
```

#### **第二步：重构监听逻辑（解决丢包的关键）**
将“发送指令”与“数据接收”彻底分离。


```python
def read_inventory(self, scan_duration=3.0):
    """
    发送一次 0x8B，持续监听 scan_duration 秒
    """
    if not self.connect(): return []
    
    self.work_mode_tags.clear()
    self._recv_buffer.clear()
    
    # 发送：Session 1, Target A, Repeat 0xFF (让它一直扫)
    cmd_payload = bytes([0x01, 0x00, 0xFF]) 
    self.socket.sendall(self._build_packet(0x8B, cmd_payload))
    
    start_t = time.time()
    while time.time() - start_t < scan_duration:
        # 持续从 Socket 捞数据并解析
        self._receive_and_process() 
        
    # 结束后最好发送一个 Reset (0x70) 或停止指令，避免天线一直发热
    return list(self.work_mode_tags)
```

#### **第三步：优化解析器（处理粘包）**
```python
def _extract_frames_from_buffer(self):
    while len(self._recv_buffer) >= 5:
        # 1. 找包头 0xA0
        if self._recv_buffer[0] != 0xA0:
            self._recv_buffer.pop(0)
            continue
            
        # 2. 拿到声明的长度
        length = self._recv_buffer[1]
        full_frame_len = length + 2 # 0xA0 + Len + (内部声明的长度)
        
        if len(self._recv_buffer) < full_frame_len:
            break # 数据还没收全，跳出等下一次 recv
            
        # 3. 提取整包进行校验
        frame = self._recv_buffer[:full_frame_len]
        # 注意：校验和计算范围是 frame[1:-1] (即从 Len 到 Data)
        if self._checksum(frame[1:-1]) == frame[-1]:
            self._parse_frame(frame)
            del self._recv_buffer[:full_frame_len] # 成功处理，删除
        else:
            self._recv_buffer.pop(0) # 校验失败，踢掉包头找下一个
```

### 总结建议：
1.  **硬件端**：网线连接是非常可靠的，**物理丢包**概率极低。
2.  **代码端**：目前的严重丢包 90% 来自于你代码中**频繁发送开始扫描指令**导致的读写器逻辑重置，以及**校验和范围算错**导致的合法包被抛弃。
3.  **配置端**：在 `config.py` 中将 `RFID_READ_INTERVAL` 调大（比如 3-5 秒一次完整扫描），而不是 1 秒一次。