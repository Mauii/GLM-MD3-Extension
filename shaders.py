from __future__ import annotations

import re
from typing import Dict


_TOKEN_PATTERN = re.compile(
    r"//[^\r\n]*|/\*.*?\*/|\"(?:\\.|[^\"\\])*\"|[{}]|[^\s{}]+",
    re.DOTALL,
)
_IGNORED_MAPS = {
    "$identitylight",
    "$lightmap",
    "$whiteimage",
    "*black",
    "*white",
}


def _normalize_shader_name(name: str) -> str:
    return name.replace("\\", "/").strip().strip('"').lower().lstrip("./")


def parse_shader_text(text: str) -> Dict[str, str]:
    tokens = [
        match.group(0)
        for match in _TOKEN_PATTERN.finditer(text)
        if not match.group(0).startswith(("//", "/*"))
    ]
    shaders: Dict[str, str] = {}
    candidate_name = None
    shader_name = None
    depth = 0
    maps = []
    index = 0

    while index < len(tokens):
        token = tokens[index]
        if token == "{":
            if depth == 0:
                shader_name = candidate_name
                maps = []
            depth += 1
            candidate_name = None
        elif token == "}":
            depth -= 1
            if depth == 0:
                diffuse_map = next(
                    (
                        map_name
                        for map_name in maps
                        if not map_name.startswith(("$", "*"))
                        and map_name.lower() not in _IGNORED_MAPS
                    ),
                    None,
                )
                if shader_name and diffuse_map:
                    shaders[_normalize_shader_name(shader_name)] = diffuse_map
                shader_name = None
        elif depth == 0:
            if not token.startswith("#"):
                candidate_name = token
        elif token.lower() in {"map", "clampmap"} and index + 1 < len(tokens):
            map_name = tokens[index + 1].strip('"')
            if map_name not in {"{", "}"}:
                maps.append(map_name)
            index += 1
        index += 1

    return shaders
