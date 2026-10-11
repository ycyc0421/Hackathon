"""跨文件行对齐：把各文件里的品名行对应起来，产出契约的 `items[]`（v0.2 新增）。

这是多品名最容易被做错的一步，因为它决定「拿谁和谁比」：

- 对齐**对了**，品名级比对才有意义；
- 对齐**错了**，比对引擎会拿着 A 文件第 2 行去比 B 文件第 3 行，然后报出一个
  看起来很正常的 CONFLICT —— 这正是我们最不能接受的失败方式（格式全对、结论全错）；
- 对齐**确定不了**，就必须说「确定不了」，而不是随便配一对继续算。

所以这里把「配不上」显式表达成 UNALIGNED：对应关系仍然记下来供人工核对，
但上层**不得**据此给出 MATCH / CONFLICT，只能给 NOT_CHECKED。

四遍扫描，优先级从高到低：

  1. 货号 / 型号完全一致          → ALIGNED，basis=ITEM_CODE，score=1.0
  2. 归一后描述词集相似度 ≥ 0.5   → ALIGNED，basis=DESCRIPTION，score=Jaccard
     （只有**没有货号**的行才走这一步：有货号的行以货号为准，
       不能因为描述像就被挂到别的货号上）
  3. 两边都有没配上的行，按行序    → **UNALIGNED**，basis=POSITION，score=null
     只记录对应关系，不给结论
  4. 剩下的单份文件独有 → PARTIAL（如提单只有整票汇总、某文件缺这一行）

**一行都不会被丢掉**：第 3 步按位置成组（第 k 行对第 k 行），不是把所有残留行
揉成一个组 —— 揉成一个组会静默丢行，那等于假装那些行不存在。

约束（与 schema 一致）：
  - 同一个 file_id 在同一个行组里最多出现一次；
  - 「一份文件里同一品名出现两次」会拆成两个行组，不会合并。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

# 描述相似度阈值：低于它就不认这对，避免"随便配一对"
DESC_MIN_SIMILARITY = 0.5

_USABLE = {"EXTRACTED", "LOW_CONFIDENCE"}


def _tokens(value) -> set[str]:
    if not value:
        return set()
    return {t for t in str(value).split() if t}


def _similarity(a, b) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _mutually_unique(a: Row, b: Row, all_rows: list[Row]) -> bool:
    """a 与 b 是否互为「各自文件里的唯一最佳」。

    为什么需要这道闸门：如果 a 所在的文件里还有另一行的描述与 b 同样像
    （典型例子：同一份发票上有「杯子 350ML 白」和「杯子 350ML 黑」两行，
    另一份文件只写了「杯子 350ML」），那么把 b 配给 a 就是**猜的**。
    这种情形必须留到位置配对那一步，判成 UNALIGNED，而不是硬配一对。
    """
    best = _similarity(a.desc, b.desc)
    for r in all_rows:
        if r is not a and r.file_id == a.file_id and _similarity(r.desc, b.desc) >= best - 1e-9:
            return False
        if r is not b and r.file_id == b.file_id and _similarity(r.desc, a.desc) >= best - 1e-9:
            return False
    return True


def _norm_code(code: str | None) -> str | None:
    """货号归一：大小写、空格、连字符都不该影响对应关系。"""
    if not code:
        return None
    cleaned = "".join(ch for ch in str(code).upper() if ch.isalnum())
    return cleaned or None


@dataclass
class Row:
    file_id: str
    file_name: str
    item_no: int
    code: str | None
    desc: str | None


@dataclass
class Group:
    members: list[dict] = field(default_factory=list)  # ItemMember 形状
    bases: list[str] = field(default_factory=list)
    codes: set[str] = field(default_factory=set)
    descs: list[str] = field(default_factory=list)
    file_ids: set[str] = field(default_factory=set)
    unresolved: bool = False

    def add(self, row: Row, basis: str | None, score: float | None) -> None:
        if row.file_id in self.file_ids:
            # 同一份文件在同一行组里只能出现一次 —— 违反说明对齐逻辑有 bug，
            # 宁可报错也不要产出「一份文件的两行是同一品名」这种假结论
            raise ValueError(f"行组内重复 file_id：{row.file_id}")
        self.members.append({"file_id": row.file_id, "item_no": row.item_no, "match_score": score})
        self.file_ids.add(row.file_id)
        if basis:
            self.bases.append(basis)
        if row.code:
            self.codes.add(row.code)
        if row.desc:
            self.descs.append(row.desc)


def _collect_rows(extractions: list[dict], doc_names: dict[str, str], ok_files: set[str]) -> list[Row]:
    rows: list[Row] = []
    for ext in extractions:
        file_id = ext["file_id"]
        if file_id not in ok_files:
            continue
        for li in ext.get("line_items") or []:
            by_key = {f["field_key"]: f for f in li.get("fields", [])}
            code = by_key.get("item_code")
            desc = by_key.get("description")
            rows.append(
                Row(
                    file_id=file_id,
                    file_name=doc_names.get(file_id, file_id),
                    item_no=li["item_no"],
                    code=_norm_code(code.get("normalized_value")) if code and code["status"] in _USABLE else None,
                    desc=desc.get("normalized_value") if desc and desc["status"] in _USABLE else None,
                )
            )
    rows.sort(key=lambda r: (r.file_id, r.item_no))
    return rows


def align_items(extractions: list[dict], documents: list[dict]) -> list[dict]:
    """返回契约 `items[]` 的字典列表。"""
    doc_names = {d["file_id"]: d["file_name"] for d in documents}
    ok_files = {d["file_id"] for d in documents if d["process_status"] == "EXTRACTED"}
    rows = _collect_rows(extractions, doc_names, ok_files)
    if not rows:
        return []

    groups: list[Group] = []
    code_counts = Counter((row.file_id, row.code) for row in rows if row.code)
    ambiguous_codes = {code for (_, code), count in code_counts.items() if count > 1}

    # ---- 第 1 遍：货号完全一致 -------------------------------------------
    for row in rows:
        if not row.code:
            continue
        target = None
        for g in groups:
            if row.code in g.codes and row.file_id not in g.file_ids:
                target = g
                break
        if target is None:
            target = Group()
            groups.append(target)
        # 同一文件重复货号时，行序只能占位，不能作为唯一对应关系。
        ambiguous = row.code in ambiguous_codes
        target.unresolved = target.unresolved or ambiguous
        target.add(row, "ITEM_CODE", None if ambiguous else 1.0)

    # ---- 第 2 遍：描述相似（只处理没有货号的行） --------------------------
    leftover: list[Row] = []
    for row in rows:
        if row.code:
            continue
        scored: list[tuple[float, Group]] = []
        for g in groups:
            if row.file_id in g.file_ids or not g.descs or not row.desc:
                continue
            best = max(_similarity(row.desc, d) for d in g.descs)
            if best >= DESC_MIN_SIMILARITY:
                scored.append((best, g))
        scored.sort(key=lambda x: x[0], reverse=True)
        if not scored:
            leftover.append(row)
            continue
        # 两个候选一样像 => 无法确定配给谁，不要随便挑一个
        if len(scored) > 1 and abs(scored[0][0] - scored[1][0]) < 1e-9:
            leftover.append(row)
            continue
        best_score, best_group = scored[0]
        if any(
            other is not row and not other.code and other.file_id == row.file_id
            and other.desc and max(_similarity(other.desc, d) for d in best_group.descs) >= best_score - 1e-9
            for other in rows
        ):
            leftover.append(row)
            continue
        scored[0][1].add(row, "DESCRIPTION", round(scored[0][0], 3))

    # 两张都没有货号的表互相配对（上面只能挂到已存在的组，组之间需要新建）
    unpaired = [r for r in leftover if not r.code]
    used: set[int] = set()
    for i, a in enumerate(unpaired):
        if i in used:
            continue
        seeds: list[tuple[float, int]] = []
        for j, b in enumerate(unpaired):
            if j in used or b.file_id == a.file_id:
                continue
            s = _similarity(a.desc, b.desc)
            if s < DESC_MIN_SIMILARITY or not _mutually_unique(a, b, unpaired):
                continue
            seeds.append((s, j))
        if not seeds:
            continue
        top = max(s for s, _ in seeds)
        seeds = [(s, j) for s, j in seeds if s >= top - 1e-9]

        g = Group()
        groups.append(g)
        g.add(a, "DESCRIPTION", round(top, 3))
        used.add(i)
        for s, j in seeds:
            g.add(unpaired[j], "DESCRIPTION", round(s, 3))
            used.add(j)

        # 还有第三份文件写了同一个品名时也要并进来。
        # 只做两两配对会把第三份文件的那行剩成 PARTIAL —— 那是假的「只有一份文件有这行」，
        # 而实际上三份文件说的都是同一个品名。
        for j, c in enumerate(unpaired):
            if j in used or c.file_id in g.file_ids:
                continue
            s = _similarity(a.desc, c.desc)
            if s >= DESC_MIN_SIMILARITY and _mutually_unique(a, c, unpaired):
                g.add(c, "DESCRIPTION", round(s, 3))
                used.add(j)

    leftover = [r for i, r in enumerate(unpaired) if i not in used] + [r for r in leftover if r.code]

    # ---- 第 3 遍：残留行按行序成组 => UNALIGNED --------------------------
    # 按位置配对而不是揉成一团：揉成一团会静默丢掉多余的行。
    by_file: dict[str, list[Row]] = {}
    for row in leftover:
        by_file.setdefault(row.file_id, []).append(row)
    files_with_rows = sorted(by_file)
    if len(files_with_rows) >= 2:
        max_len = max(len(v) for v in by_file.values())
        consumed: set[int] = set()
        for k in range(max_len):
            slot = [by_file[f][k] for f in files_with_rows if k < len(by_file[f])]
            if len(slot) < 2:
                continue  # 这个位置上只有一份文件有行，交给第 4 步按 PARTIAL 处理
            g = Group(unresolved=True)
            groups.append(g)
            for row in slot:
                g.add(row, "POSITION", None)
                consumed.add(id(row))
        leftover = [r for r in leftover if id(r) not in consumed]

    # ---- 第 4 遍：单份文件独有的行 => PARTIAL ---------------------------
    for row in leftover:
        g = Group()
        groups.append(g)
        g.add(row, None, None)

    return [_to_item(index, g, doc_names) for index, g in enumerate(groups, start=1)]


def _to_item(index: int, g: Group, doc_names: dict[str, str]) -> dict:
    members = sorted(g.members, key=lambda m: m["file_id"])
    if g.unresolved and len(members) >= 2:
        status, basis = "UNALIGNED", "POSITION"
        note = (
            "单证间的品名行缺少唯一对应关系（如货号重复或描述相近），"
            "无法确定哪一行对应哪一行，不据此给出比对结论。请人工核对。"
        )
    elif len(members) >= 2:
        status, basis, note = "ALIGNED", _dominant_basis(g), None
    else:
        status, basis = "PARTIAL", _dominant_basis(g)
        only = doc_names.get(members[0]["file_id"], members[0]["file_id"])
        note = (
            f"只有 {only} 提供了这一品名行，其余文件没有对应行"
            "（提单等单证可能只给整票汇总，也可能是漏列），无法交叉比对。"
        )
    return {
        "item_id": f"itm_{index}",
        "label": _label_of(g),
        "alignment_status": status,
        "alignment_basis": basis,
        "alignment_note": note,
        "members": members,
    }


def _dominant_basis(g: Group) -> str | None:
    if not g.bases:
        return None
    if "ITEM_CODE" in g.bases:
        return "ITEM_CODE"
    if "DESCRIPTION" in g.bases:
        return "DESCRIPTION"
    return g.bases[0]


def _label_of(g: Group) -> str:
    if g.descs:
        # 取最短的那条描述做标题：通常是最干净的写法，不会把包装说明混进来
        return min(g.descs, key=len)
    if g.codes:
        return sorted(g.codes)[0]
    return "未命品名"
