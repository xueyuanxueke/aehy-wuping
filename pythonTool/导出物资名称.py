# -*- coding: utf-8 -*-
"""从 BuildUtil$$.cctor 提取 Wuping 枚举 → 名称信息表（可复用，换版本只改 --version-dir）

产物布局（与运行时一致，**固定 7 槽**，缺失项为空串，不要裁剪/去重）：
    [0] 图标路径   [1] 简体名   [2] 繁体名   [3] 英文名
    [4] 描述简体   [5] 描述繁体 [6] 描述英文

原理
----
`BuildUtil.cctor` 里对 `cailiaoSpriteMap`（`Dictionary<Wuping, string[]>`）逐条 Add，
每个条目是现造一个 `string[]` 再填元素：

    mov  r1, #7                 ; 数组长度（实测 489/490 条为 7，个别 5）
    bl   il2cpp_codegen_array_new
    mov  r5, r0                 ; r5 = 新数组
    ; 元素 i：取字面量 → 写 [r5, #0x10 + 4*i]
    ldr  r1, [pc, #-0x1f0]      ; 池字 = 相对偏移
    ldr  r1, [pc, r1]           ; → GOT 项（内容 = 字面量槽地址，由 R_ARM_RELATIVE 填入）
    ldr  r6, [r1]               ; → Il2CppString*
    str  r6, [r5, #0x14]
    ; 收尾
    mov  r0, r4                 ; this = 字典
    mov  r1, #<Wuping 值>       ; key
    mov  r2, r5                 ; value = string[]
    bl   Dictionary<Int32Enum,object>.Add

所以：字面量槽地址 ↔ 字符串取自 Il2CppDumper 的 stringliteral.json（键就是槽 VA）；
GOT 项 ↔ 槽地址取自 .rel.dyn 的 R_ARM_RELATIVE（REL 型的加数存在目标地址文件内容里）。
据此做一次轻量寄存器模拟，就能把 key 与数组元素一一对上，无需猜命名、无需人工对齐。

用法
----
    python 导出物资名称.py                          # 默认读 261030
    python 导出物资名称.py --version-dir D:\\...\\261030 --csv out.csv
"""
from __future__ import annotations

import argparse
import json
import os
import re
import struct
import sys

try:
    from elftools.elf.elffile import ELFFile
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB
except ImportError:  # pragma: no cover
    sys.exit("需要 pyelftools 与 capstone：pip install pyelftools capstone")

DEFAULT_VERSION = os.environ.get("AEHY_VERSION_DIR", r"D:\Game\Unity\aehy\261030")
DEFAULT_OUT = r"D:\Game\Unity\aehy\aehy-mod-master\tools\place_out\wuping_names.json"

SLOT_NAME = ["图标路径", "简体名", "繁体名", "英文名", "描述简体", "描述繁体", "描述英文"]
REG_ALIAS = {"sp": 13, "lr": 14, "pc": 15, "ip": 12, "fp": 11, "sb": 9, "sl": 10}
MEM_RE = re.compile(r"^(\w+),\s*\[([^\]]+)\](!?)\s*(?:,\s*(#?[\w\-]+))?$")


# --------------------------------------------------------------------------- ELF
class Elf(object):
    def __init__(self, path):
        self.f = open(path, "rb")
        self.e = ELFFile(self.f)
        self.segs = [(s["p_vaddr"], s["p_vaddr"] + s["p_filesz"], s["p_offset"])
                     for s in self.e.iter_segments() if s["p_type"] == "PT_LOAD"]
        self.is64 = self.e.get_machine_arch() == "AArch64"

    def read(self, va, n=4):
        for a, b, o in self.segs:
            if a <= va < b:
                self.f.seek(o + (va - a))
                return self.f.read(n)
        return None

    def u32(self, va):
        b = self.read(va, 4)
        return struct.unpack("<I", b)[0] if b else None

    def u64(self, va):
        b = self.read(va, 8)
        return struct.unpack("<Q", b)[0] if b else None

    def reloc_addend_map(self):
        """重定位目标地址 → 该处的初始指针值（即 REL 型加数）。

        只关心"指向字符串字面量槽"的 GOT 项，调用方按槽区间过滤。
        """
        out = {}
        for secname in (".rel.dyn", ".rela.dyn"):
            sec = self.e.get_section_by_name(secname)
            if not sec:
                continue
            for r in sec.iter_relocations():
                off = r["r_offset"]
                add = None
                try:
                    add = r["r_addend"]
                except Exception:
                    add = None
                if add is None:                      # REL：加数存在目标地址内容里
                    add = self.u64(off) if self.is64 else self.u32(off)
                if add is not None:
                    out[off] = add
        return out


# --------------------------------------------------------------------- 脚本信息
def load_script(dumper_dir):
    with open(os.path.join(dumper_dir, "script.json"), encoding="utf-8") as f:
        return json.load(f)


def find_method(script, pred):
    """按谓词找方法地址；同名取最小地址。"""
    hits = [m for m in script["ScriptMethod"] if pred(m["Name"])]
    return min(m["Address"] for m in hits) if hits else None


def func_end(script, addr):
    addrs = sorted(set(script["Addresses"]) | {m["Address"] for m in script["ScriptMethod"]})
    import bisect
    i = bisect.bisect_right(addrs, addr)
    return addrs[i] if i < len(addrs) else addr + 0x10000


# ------------------------------------------------------------------ 寄存器模拟
def regnum(tok):
    tok = tok.strip().strip("{}[]")
    if tok in REG_ALIAS:
        return REG_ALIAS[tok]
    m = re.fullmatch(r"r(\d+)", tok)
    return int(m.group(1)) if m else -1


def parse_mem(op):
    """`str/ldr` 操作数 → (reg, base, index_reg, offset)"""
    m = MEM_RE.match(op.strip())
    if not m:
        return None
    dst = regnum(m.group(1))
    inner = [x.strip() for x in m.group(2).split(",")]
    base = regnum(inner[0])
    idx, off = -1, None
    if len(inner) >= 2:
        t = inner[1]
        if t.startswith("#"):
            try:
                off = int(t[1:], 0)
            except ValueError:
                off = None
        else:
            idx = regnum(t)
    return dst, base, idx, off


def detect_arrnew(words, base, known_methods):
    """il2cpp_array_new 没有托管名，只能按调用形态认：
    bl 之前 6 条内有 `mov r1,#len`，且目标不在 script.json 的方法表里。
    与 文档/逆向_陷阱与猎物区域/工具/tt2.py 同一套判据。"""
    env = os.environ.get("AEHY_ARRNEW", "")
    if env:
        return int(env, 16)
    cnt, pend = {}, None
    for i, x in enumerate(words):
        c = x & 0x0FFFFFFF
        rd = (x >> 12) & 0xF
        if (c & 0x0FFF0000) == 0x03A00000 or (c & 0x0FF00000) == 0x03000000:
            if rd == 1:
                pend = i
            continue
        if (c & 0x0FFF0FF0) == 0x01A00000:
            if rd == 1 or (x & 0xF) == 1:
                pend = i
            continue
        if (c & 0x0F000000) == 0x0B000000:
            off = c & 0x00FFFFFF
            if off & 0x00800000:
                off -= 0x01000000
            tgt = base + i * 4 + 8 + off * 4
            if pend is not None and i - pend <= 6 and tgt not in known_methods:
                cnt[tgt] = cnt.get(tgt, 0) + 1
            pend = None
    return max(cnt.items(), key=lambda kv: kv[1])[0] if cnt else 0


def emulate(elf, script, dumper_dir, verbose=True):
    """返回 groups: [{ctor_at, items:[(key, [7 元素], add_at, 数组长度)]}]"""
    cctor = find_method(script, lambda n: n.endswith("BuildUtil$$.cctor") or n.endswith("BuildUtil___cctor"))
    if cctor is None:
        raise SystemExit("script.json 里找不到 BuildUtil$$.cctor")
    add = find_method(script, lambda n: "Dictionary<Int32Enum, object>$$Add" in n)
    dctor = find_method(script, lambda n: "Dictionary<Int32Enum, object>$$.ctor" in n)
    known = {m["Address"] for m in script["ScriptMethod"]}
    if add is None or dctor is None:
        raise SystemExit("找不到 Dictionary<Int32Enum,object> 的 Add/.ctor（版本差异？）")

    sl_path = os.path.join(dumper_dir, "stringliteral.json")
    literals = {}
    with open(sl_path, encoding="utf-8") as f:
        for it in json.load(f):
            try:
                literals[int(it["address"], 16)] = it.get("value", "")
            except (KeyError, TypeError, ValueError):
                continue
    if not literals:
        raise SystemExit("stringliteral.json 为空或格式不认识")
    lo, hi = min(literals), max(literals)

    got = {}
    for tgt, addend in elf.reloc_addend_map().items():
        if lo <= addend <= hi:
            got[tgt] = addend

    md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    end = func_end(script, cctor)
    code = elf.read(cctor, end - cctor)
    if not code:
        raise SystemExit("cctor 地址不在任何 PT_LOAD 段内：%#x" % cctor)
    nw = len(code) // 4
    words = struct.unpack("<%dI" % nw, code[:nw * 4])
    arrnew = detect_arrnew(words, cctor, known)

    regs, arrs, arrlen = {}, {}, {}
    stack = {}
    nid = [0]
    groups, cur = [], None
    pending_len = [None]
    stat = {"bl": 0, "ldr_pc": 0, "mem_unparsed": 0, "str_arr": 0}

    def kill(r):
        if r >= 0:
            regs.pop(r, None)

    for ins in md.disasm(code, cctor):
        mn, op, a = ins.mnemonic, ins.op_str, ins.address

        if mn == "bl" or mn == "blx":
            stat["bl"] += 1
            try:
                t = int(op.lstrip("#"), 16)
            except ValueError:
                t = -1
            if t == dctor:
                cur = {"ctor_at": a, "items": []}
                groups.append(cur)
            elif arrnew and t == arrnew:            # 数组分配：记下声明长度
                v1 = regs.get(1)
                if v1 and v1[0] == "c":
                    pending_len[0] = v1[1]
            elif t == add and cur is not None:
                k, v = regs.get(1), regs.get(2)
                key = k[1] if k and k[0] == "c" else None
                elems, L = [], None
                if v and v[0] == "arr":
                    d = arrs.get(v[1], {})
                    L = arrlen.get(v[1])
                    if d:
                        elems = [d.get(i) for i in range(max(d) + 1)]
                cur["items"].append((key, elems, a, L))
            for r in (0, 1, 2, 3, 12, 14):          # AAPCS：调用破坏 r0-r3/r12/lr
                kill(r)
            continue

        if mn in ("mov", "movs", "movw", "movt"):
            p = [x.strip() for x in op.split(",")]
            if len(p) != 2:
                continue
            dst = regnum(p[0])
            if dst < 0:
                continue
            if p[1].startswith("#"):
                try:
                    val = int(p[1][1:], 0)
                except ValueError:
                    kill(dst)
                    continue
                if mn == "movt":
                    old = regs.get(dst)
                    base = old[1] if old and old[0] == "c" else 0
                    regs[dst] = ("c", (base & 0xFFFF) | (val << 16))
                else:
                    regs[dst] = ("c", val & 0xFFFFFFFF)
            else:
                src = regnum(p[1])
                kill(dst)
                if src in regs:
                    regs[dst] = regs[src]
            continue

        if mn in ("add", "adds", "sub", "subs", "addw", "subw"):
            p = [x.strip() for x in op.split(",")]
            dst = regnum(p[0])
            if dst < 0:
                continue
            if len(p) >= 3 and p[2].startswith("#"):
                src = regnum(p[1])
                try:
                    val = int(p[2][1:], 0)
                except ValueError:
                    kill(dst)
                    continue
                st = regs.get(src)
                if st and st[0] == "c":
                    v = st[1] + val if mn.startswith("add") else st[1] - val
                    regs[dst] = ("c", v & 0xFFFFFFFF)
                else:
                    kill(dst)
            else:
                kill(dst)
            continue

        if mn in ("ldr", "ldrb", "ldrh", "ldrsb", "ldrsh"):
            r = parse_mem(op)
            if not r:
                stat["mem_unparsed"] += 1
                continue
            dst, base, idx, off = r
            if base == 15 and idx >= 0:                       # ldr rX,[pc,rY]
                stat["ldr_pc"] += 1
                src = regs.get(idx)
                kill(dst)
                if src and src[0] == "off":
                    tgt = (a + 8 + src[1]) & 0xFFFFFFFF
                    regs[dst] = ("slot", got[tgt]) if tgt in got else ("heap", tgt)
                continue
            if base == 15:                                    # ldr rX,[pc,#imm]
                w = struct.unpack("<I", ins.bytes)[0]
                if (w & 0x0F7F0000) != 0x051F0000 or off is None:
                    kill(dst)
                    continue
                imm = w & 0xFFF
                if not (w >> 23) & 1:
                    imm = -imm
                W = elf.u32(a + 8 + imm)
                regs[dst] = ("off", W) if W is not None else ("heap", 0)
                continue
            if base == 13 and idx < 0 and off is not None:     # ldr rX,[sp,#imm]
                kill(dst)
                if off in stack:
                    regs[dst] = stack[off]
                continue
            if idx >= 0 or off is not None:
                kill(dst)
                continue
            src = regs.get(base)                              # ldr rX,[rY]
            kill(dst)
            if src and src[0] == "slot":
                regs[dst] = ("str", literals.get(src[1], ""))
            continue

        if mn in ("str", "strb"):
            r = parse_mem(op)
            if not r:
                stat["mem_unparsed"] += 1
                continue
            src, base, idx, off = r
            if base == 13 and idx < 0 and off is not None:     # str rX,[sp,#imm]
                if src in regs:
                    stack[off] = regs[src]
                else:
                    stack.pop(off, None)
                continue
            if off is None or off < 0x10 or (off - 0x10) % 4:
                continue
            st = regs.get(base)
            if not st or st[0] != "arr":
                nid[0] += 1
                st = ("arr", nid[0])
                regs[base] = st
                arrs[st[1]] = {}
                arrlen[st[1]] = pending_len[0]
                pending_len[0] = None
            v = regs.get(src)
            arrs[st[1]][(off - 0x10) // 4] = v[1] if v and v[0] == "str" else None
            stat["str_arr"] += 1
            continue

        if mn == "pop":
            for t in op.strip("{}").split(","):
                kill(regnum(t))
            continue

    if verbose:
        print("cctor %#x..%#x  Add@%#x ctor@%#x array_new=%s" %
              (cctor, end, add, dctor, ("%#x" % arrnew) if arrnew else "未探测到"))
        print("字面量槽 %d 条；GOT 项 %d 个；数组元素写入 %d 次" %
              (len(literals), len(got), stat["str_arr"]))
    return groups


def pick_group(groups, log=print):
    """cailiaoSpriteMap 是条目最多的那组，并用图标路径做一次合理性校验。"""
    cand = [g for g in groups if g["items"]]
    if not cand:
        raise SystemExit("没解出任何字典条目")
    best = max(cand, key=lambda g: len(g["items"]))
    first = next((it for it in best["items"] if it[0] == 0), None)
    if first and first[1] and not re.search(r"(UI/|/)", str(first[1][0])):
        log("警告：条数最多的一组首元素不像图标路径：%r" % (first[1][0],))
    log("字典分组：%d 组 / 共 %d 条；选中条目最多的一组（%d 条，ctor@%#x）" %
        (len(groups), sum(len(g["items"]) for g in groups), len(best["items"]), best["ctor_at"]))
    return best


def enum_values(dump_cs, name="Wuping"):
    """从 dump.cs 读枚举成员，用于报告缺口。"""
    vals = {}
    try:
        with open(dump_cs, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return vals
    for mm in re.finditer(r"public const %s (\w+) = (-?\d+);" % re.escape(name), text):
        vals[int(mm.group(2))] = mm.group(1)
    return vals


def fill_mapping(path, table):
    """把 物资映射.csv 里名称为空的行按编号补上简中名（只填空，不动已有内容）。"""
    import csv
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0].keys()) if rows else []
    if "名称" not in fields or "编号" not in fields:
        print("跳过 %s：缺 名称/编号 列" % path)
        return
    n = 0
    for r in rows:
        if (r.get("名称") or "").strip():
            continue
        try:
            k = str(int(r["编号"]))
        except (TypeError, ValueError):
            continue
        v = table.get(k)
        nm = v[1] if v and len(v) > 1 else ""
        if nm:
            r["名称"] = nm
            n += 1
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print("已补齐 %s 的 %d 行名称" % (path, n))


def main(argv=None):
    ap = argparse.ArgumentParser(description="从 libil2cpp 提取 Wuping → 名称/描述表")
    ap.add_argument("--version-dir", default=DEFAULT_VERSION,
                    help="含 libil2cpp.so 与 global-metadata.dat 的版本目录")
    ap.add_argument("--dumper-dir", default=None,
                    help="Il2CppDumper 输出目录（含 dump.cs/script.json/stringliteral.json）")
    ap.add_argument("--out", default=DEFAULT_OUT, help="输出 JSON（默认写回 place_out/wuping_names.json）")
    ap.add_argument("--csv", default=None, help="可选：另存一份 CSV")
    ap.add_argument("--fill-csv", default=None,
                    help="可选：把名称为空的 物资映射.csv 按本表补齐（只填空单元格，幂等）")
    ap.add_argument("--dry-run", action="store_true", help="只打印统计，不写文件")
    args = ap.parse_args(argv)

    vdir = os.path.abspath(args.version_dir)
    ddir = args.dumper_dir or os.path.join(vdir, "Il2CppDumper-out")
    script = load_script(ddir)

    elf = Elf(os.path.join(vdir, "libil2cpp.so"))
    if elf.is64:
        raise SystemExit("当前只实现了 ARM32（armeabi-v7a）；遇到 AArch64 需扩展模拟器")

    groups = emulate(elf, script, ddir)
    grp = pick_group(groups)

    table = {}
    unresolved = 0
    mismatched = 0
    for key, elems, add_at, length in grp["items"]:
        if key is None:
            continue
        row = [(e if e is not None else "") for e in elems]
        unresolved += sum(1 for e in elems if e is None)
        if length is not None and length != len(row):
            mismatched += 1
        table[key] = row

    ev = enum_values(os.path.join(ddir, "dump.cs"))
    keys = sorted(table)
    missing = sorted(set(ev) - set(table)) if ev else []
    print("解出 %d 条，key %d..%d；枚举 %d 个成员，缺 %d 个%s" %
          (len(table), keys[0], keys[-1], len(ev), len(missing),
           ("：" + ", ".join("%d(%s)" % (k, ev[k]) for k in missing[:12])) if missing else ""))
    print("未能解析的元素（空串占位）：%d" % unresolved)
    if mismatched:
        print("警告：%d 条的声明长度与实际写入不一致（可能漏写/越界）" % mismatched)
    bad = [k for k, v in table.items() if len(v) < 4 or not v[1]]
    if bad:
        print("警告：%d 条缺少简中名或槽位不足，例如 %s" % (len(bad), bad[:8]))
    dist = {}
    for v in table.values():
        dist[len(v)] = dist.get(len(v), 0) + 1
    print("槽位长度分布：%s" % dict(sorted(dist.items())))

    if args.dry_run:
        return 0

    out = {"%d" % k: table[k] for k in keys}
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("已写入 %s" % args.out)

    if args.csv:
        import csv
        with open(args.csv, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "枚举名"] + SLOT_NAME)
            for k in keys:
                w.writerow([k, ev.get(k, "")] + table[k])
        print("已写入 %s" % args.csv)

    if args.fill_csv:
        fill_mapping(args.fill_csv, table)
    return 0


if __name__ == "__main__":
    sys.exit(main())
