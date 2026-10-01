"""Exact S11 audio text and approved block/scene structure from the Content Pack."""
from __future__ import annotations

import re

BLOCK_STARTS = (
    "Привет. Позвольте представить вам",
    "Чтобы понять, как работают новые функции",
    "Итак, у нас имеется запись собрания",
    "После выбора дорожек нам доступны два режима",
    "Здесь мы можем выбрать дорожки",
    "После выбора нужных дорожек кнопка",
    "Теперь рассмотрим второй режим",
    "Все дорожки расположены на общей временной шкале",
    "Теперь перейдём непосредственно к монтажу записи",
    "После завершения монтажа можно создать готовый файл",
    "Теперь перейдём к Аудиоархиву",
    "Сохранить исходную запись в Аудиоархив можно не только",
    "После обработки записи в режиме «Анонс-мейкер»",
    "Чтобы найти ранее сохранённую запись",
)


def sections(pack: str) -> tuple[str, str, str]:
    try:
        part_a = pack.split("# PART A · Approved Final Russian Narration", 1)[1].split("# PART B", 1)[0]
        part_b = pack.split("# PART B · Approved Semantic Storyboard", 1)[1].split("# PART C", 1)[0]
        part_c = pack.split("# PART C · Approved Technical Scene Map", 1)[1].split("# PART D", 1)[0]
    except IndexError as error:
        raise ValueError("approved PART A/B/C sections missing") from error
    lines = [line for line in part_a.splitlines()
             if not line.startswith("# ") and not line.startswith("## ") and line.strip() != "---"]
    narration = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return narration, part_b, part_c


def approved_structure(pack: str) -> tuple[str, list[dict]]:
    narration, part_b, part_c = sections(pack)
    titles = re.findall(r"(?m)^## (B\d{2}) · (.+)$", part_b)
    if len(titles) != 14 or [bid for bid, _ in titles] != [f"B{i:02d}" for i in range(1, 15)]:
        raise ValueError("approved block title map missing")
    scene_map = {}
    for bid, contents in re.findall(r"(?m)^- (B\d{2}): (.+)$", part_c):
        units = re.findall(r"(?:^|; )([0-9]{3})(?: |$)", contents)
        # The first unit can be followed by an action; subsequent units follow semicolons.
        scene_map[bid] = [(int(number), description.strip()) for number, description in
                          re.findall(r"(?:^|; )([0-9]{3}) (.*?)(?=; [0-9]{3} |$)", contents)]
        if len(units) != len(scene_map[bid]):
            raise ValueError(f"invalid scene syntax: {bid}")
    starts = []
    for anchor in BLOCK_STARTS:
        if narration.count(anchor) != 1:
            raise ValueError(f"missing or ambiguous block boundary: {anchor}")
        starts.append(narration.index(anchor))
    if starts[0] != 0 or starts != sorted(starts):
        raise ValueError("block order differs from approved narration")
    blocks = []
    for index, (bid, title) in enumerate(titles):
        start = starts[index]
        end = starts[index + 1] if index + 1 < len(starts) else len(narration)
        text = narration[start:end].rstrip()
        units = scene_map.get(bid)
        if not text or not units:
            raise ValueError(f"missing narration or scene map: {bid}")
        blocks.append({"id": bid, "title": title, "start": start, "end": start + len(text),
                       "narration": text, "scene_units": units})
    numbers = [number for block in blocks for number, _ in block["scene_units"]]
    if numbers != list(range(1, 55)):
        raise ValueError("approved 54 scene unit map changed")
    if any(narration[blocks[i]["end"]:blocks[i + 1]["start"]].strip() for i in range(13)):
        raise ValueError("non-whitespace gap between blocks")
    return narration, blocks
