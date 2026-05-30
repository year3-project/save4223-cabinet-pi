# RFID Missed-Read Debug Report

Branch base: `fix-rfid-nfc-issues` @ `9abda23`. Reviewed the full `RFIDReader`
implementation in `src/hardware/raspberry_pi.py`, the live read path
(`main.py` → `read_rfid_tags_inventory`), the param-sweep scripts
(`test_rfid_params.py`, `test_freq_params.py`, `stress_rfid.py`), and the
manual analysis in `RFID_issues.md`.

**No hardware was connected during this review** — code findings are verified
statically; tuning recommendations are hypotheses to confirm on the reader.

---

## 1. 🚨 Do NOT apply the checksum change suggested in `RFID_issues.md`

`RFID_issues.md` is internally contradictory. Section 1 correctly states the
manual requires the checksum to **include** the `0xA0` header
("校验和包含包头 0xA0 在内的所有字节"), but its later "第二步/Section B"
fix computes the checksum **excluding** `0xA0` (`frame[1:-1]`).

The current code is **correct** — it includes `0xA0`:
- TX: `_build_packet` → `_checksum(packet_wo_checksum)` where the buffer starts with `0xA0` (`raspberry_pi.py:356-367`)
- RX: `_extract_frames_from_buffer` → `_checksum(frame[:-1])` (`raspberry_pi.py:985`)

This matches the manual and commit `296316c`. **Applying the "exclude 0xA0"
version would make every checksum mismatch → 0 tags read.** Leave `_checksum`
and `_build_packet` alone.

> Note: the docstring on `_checksum` (`:352`) says "exclude 0xA0 header" — that
> comment is wrong, but the behavior (include) is right. Comment-only defect.

---

## 2. Diagnosis of the 35/39 ceiling

Your own `test_rfid_params.py` header already establishes what the problem is **not**:

| Lever tried | Result |
|---|---|
| Power → 33 dBm (max) | no improvement |
| Increasing duration / passes | no improvement beyond 35 |
| Second antenna (0x01) | tags are a **subset** of antenna 0 — no union gain |
| 0x8A fast-switch | 36 (marginal) |

A ceiling that is **stable at ~35 and never moves with more time or power** is
**not a decode bug** (a decode bug drops a fraction or a specific EPC length, it
doesn't plateau) and **not a dwell-time problem**. The 4 missing tags are one of:

1. **Gen2 session-state hiding** — once a tag is inventoried, its session flag
   flips to B and it goes quiet for the session's persistence window. A tag that
   always loses collision arbitration in S1 may answer in a different session.
   *(This is your hypothesis — it is plausible and worth the multi-session scan.)*
2. **Physically under-powered tags** — antenna null, deep metal shadow, or tags
   pressed flat against metal / each other (detuning). **No protocol change can
   read a tag that isn't backscattering enough to be heard.**

---

## 3. Decode bugs found and fixed

| Location | Bug | Fix |
|---|---|---|
| `_parse_tag_data_bytes` (`:1089`) | `rssi_dbm = rssi_byte - 129 if rssi_byte < 129 else rssi_byte - 129` — both branches identical (copy-paste no-op) | Simplified to `rssi_byte - 129`; log now also shows the raw byte |
| `_parse_frame` (`:1041`) | End-of-inventory **status frames** (`0x8B`/`0x8A`, 7-byte odd payload: AntID+ReadRate+TotalRead) were fed to the tag parser → phantom tags / polluted voting counts | Added an **odd-length guard**: a real tag record is always even length (`freq(1)+PC(2)+EPC(2·words)+RSSI(1)`), so odd payloads are skipped as status frames |

Neither bug explains the 4 missing tags, but both are real correctness issues.
Verified with synthetic frames: a 7-byte status frame now yields no phantom tag,
while a normal 96-bit EPC frame still decodes.

---

## 4. Change made: multi-session union in the production path

Previously multi-session only existed in `test_rfid_params.py`. It is now wired
into the live scan (`main.py` → `read_rfid_tags_inventory`), **opt-in via config**.

**New code** (`raspberry_pi.py`):
- `read_rfid_tags_multisession(sessions, antennas, duration_per_combo, ...)` —
  connects once, loops `session × antenna`, unions results, sorts by detection count.
- `_scan_session_antenna(session, antenna, duration)` — one 0x8B scan pinned to a
  fixed Gen2 session, toggling Target A/B (mirrors the proven `scan_with_session`).
- `read_rfid_tags_inventory(..., sessions=...)` delegates to the multi-session scan
  when `len(sessions) > 1`; otherwise behavior is **unchanged** (fast-switch / continuous).

**Config** (`config.json` → `rfid_inventory`):
```json
"sessions": [0,1,2,3]
```
- Total scan time ≈ `len(sessions) × len(antennas) × pass_duration`.
- Since antenna 1 is a subset of antenna 0 here, **set `antennas: [0]` when using
  multi-session** → with `[0,1,2,3] × [0] × 3s ≈ 12s`.
- To revert: remove `sessions` or set `[1]` → back to dual-antenna fast-switch (0x8A).

Backward-compatible: when `sessions` is absent or single-valued, nothing changes.

---

## 5. The most promising UNTRIED lever: sweep power DOWN

You have only swept power **upward** (30 → 33 dBm). Your own code comment says:

> *"33dBm causes RX overload and self-jamming in metal cabinets"* (`_init_reader`)

In a sealed metal cabinet, **max power can desensitize the reader front-end** and
deepen multipath nulls, masking weak/shadowed tags. Counterintuitively, **lower**
power (24–28 dBm) sometimes recovers exactly the kind of stubborn tags you're
missing. Recommend a downward sweep (`0x18`/24 → `0x1A`/26 → `0x1C`/28 dBm) crossed
with the multi-session scan. (Easy to add to `test_rfid_params.py`.)

---

## 6. Needs hardware verification / honest expectations

- Multi-session may recover **1–2** of the 4 (the per-session scan already toggles
  Target A *and* B, so pure "S1-B hiding" tags should partly be caught already).
- If 2–3 tags still never appear across all sessions **and** a downward power
  sweep, the remaining gap is **physical** (antenna coverage / metal shadow) and
  needs a hardware fix: reposition/re-angle the antenna, add a third antenna
  orientation, or move those tags off direct metal contact.

## Files changed
- `src/hardware/raspberry_pi.py` — 2 decode fixes + multi-session methods
- `src/main.py` — pass `sessions` from config
- `config.json` — `sessions` knob + guidance

---

## Addendum: verified against the manual (V4.1.7) + round-2 fixes

Cross-checked every claim against `UHF RFID读写器通讯协议用户手册_V4.1.7.pdf`:

| Item | Manual | Verdict |
|---|---|---|
| Checksum | p.42 C-code: `uSum=Σall; (~uSum)+1`; "除校验和本身外所有字节" includes 0xA0 | code **correct** — do NOT exclude 0xA0 |
| `Len` | "Len 后面开始的字节数" = data+3 | correct |
| Tag frame 0x8B/0x8A | `FreqAnt(1) PC(2) EPC(N) RSSI(1)` | decoder correct |
| RSSI | table: `0x62=-31dBm`, 1:1 step → `byte-129` | correct |
| **0x8A end frame** | `Len=0x0A` → `TotalRead(3)+CommandDuration(4)` = **7 bytes (odd)** | **this is the `0000` phantom source** |

**Key correction:** the `0000` phantom comes from the **0x8A end frame**, whose
payload is 7 bytes — **odd** — so the odd-length guard added above **does fix it**
(verified: a crafted `0x8A` end frame now yields no tag). The `IGNORED_TAGS`
`"0000"` blacklist is now redundant. All status/end frames are either odd
(guarded) or <6 bytes (can't form a tag), so **status-frame false reads are fully
covered**.

**Round-2 fixes (this commit):**
- **#7 missed reads** — `_idle_break_timeout` default `2.0 → 0.3`s (a 2s idle wait
  per cycle was starving scan rounds) and continuous-scan `repeat 0x01 → 0x0A`
  (more anti-collision rounds per command).
- **#8 fd leak** — `connect()` now closes any prior socket first (the single-antenna
  path connected twice and orphaned the first socket every scan).
- **#A Flash wear** — power/frequency are written to the reader's Flash and persist
  across power-off; `_init_reader()` now runs **once per process** (`_reader_configured`)
  instead of on every connect (0x76 takes >100ms and wears Flash).

**Latent risks noted (not bugs today):**
- Enabling **Phase** adds 2 bytes/tag to the frame; the decoder doesn't handle it
  → would misparse. Don't enable Phase without updating `_parse_tag_data_bytes`.
- The 0x8A **short** command (used here, `Len=0x0D`) cannot set session/target; it
  uses the reader default. Multi-session uses 0x8B (correct), not 0x8A.
