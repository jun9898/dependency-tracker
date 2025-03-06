import ast
import argparse
from pathlib import Path
import sys

# 폴더별 노드 색상 매핑 (원하는대로 수정 가능)
FOLDER_COLOR_MAP = {
    "base": "#f8b195",
    "bots": "#f67280",
    "utils": "#c06c84",
    "root": "#355c7d",  # 프로젝트 루트에 있는 파일은 root 색상
}

def get_internal_modules(project_root: Path):
    """
    프로젝트 루트 내의 모든 파이썬 파일(단, .venv 폴더와 파일명이 '__'로 시작하는 파일 제외)을 탐색하여,
    모듈 이름(도트 표기)과 해당 파일의 relative note path(확장자 제외)를 dict로 반환합니다.
    
    예시)
      "base.constant" -> "base/constant"
    """
    modules = {}
    for filepath in project_root.rglob("*.py"):
        # .venv 폴더 제외
        if ".venv" in filepath.parts:
            continue
        # 파일명이 "__"로 시작하면 건너뜁니다.
        if filepath.name.startswith("__"):
            continue
        rel_path = filepath.relative_to(project_root)
        if filepath.name == "__init__.py":
            # __init__.py는 디렉토리 이름을 모듈명으로 사용
            if rel_path.parent == Path("."):
                mod_name = project_root.name
            else:
                mod_name = rel_path.parent.as_posix().replace("/", ".")
        else:
            mod_name = rel_path.with_suffix("").as_posix().replace("/", ".")
        # note로 생성할 때는 확장자 없이 relative path (예: base/constant)
        modules[mod_name] = rel_path.with_suffix("").as_posix()
    return modules

def parse_imports(filepath: Path, internal_modules: dict):
    """
    파이썬 파일을 파싱하여 import 구문을 읽고,
    내부 모듈(내부_modules에 포함되는 경우)과 그 외(내장 모듈이나 .venv 라이브러리 등)를 분리하여 반환합니다.
    
    반환:
      internal_deps: set of 내부 모듈 이름 (내부 노드 링크 생성)
      external_deps: set of 외부 모듈의 최상위 이름 (예: os, pandas 등)
    """
    try:
        source = filepath.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        print(f"Error reading {filepath}: {e}", file=sys.stderr)
        return set(), set()
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as e:
        print(f"Syntax error in {filepath}: {e}", file=sys.stderr)
        return set(), set()
    
    internal_deps = set()
    external_deps = set()
    
    def is_internal(module_str):
        # 직접 internal_modules에 key로 존재하는지 확인
        if module_str in internal_modules:
            return module_str
        # 예를 들어 "bots"라고만 적었을 때, 내부 모듈 "base.bots"가 있다면 그것으로 매칭
        for key in internal_modules.keys():
            if key.endswith("." + module_str):
                return key
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name  # 예: "os", "base.constant", "pandas"
                internal_match = is_internal(mod)
                if internal_match:
                    internal_deps.add(internal_match)
                else:
                    # 외부 모듈은 최상위 이름만 취함
                    external_deps.add(mod.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            module = node.module  # 예: "base.logistics" 또는 None (상대 import)
            level = node.level    # 상대 import 수준 (0이면 절대)
            # 상대 import는 내부로 간주
            if level > 0:
                mod_full = module if module else ""
            else:
                mod_full = module if module else ""
            for alias in node.names:
                if alias.name == "*":
                    continue
                if mod_full:
                    candidate = f"{mod_full}.{alias.name}"
                else:
                    candidate = alias.name
                internal_match = is_internal(candidate)
                if internal_match:
                    internal_deps.add(internal_match)
                else:
                    # 내부 모듈이 아니면, 모듈 전체(절대 import)로 처리
                    if mod_full:
                        internal_match = is_internal(mod_full)
                        if internal_match:
                            internal_deps.add(internal_match)
                        else:
                            external_deps.add(mod_full.split('.')[0])
                    else:
                        external_deps.add(alias.name.split('.')[0])
    return internal_deps, external_deps

def get_color_for_node(note_rel_path: str) -> str:
    """
    note의 relative 경로에서 최상위 폴더를 추출하여, 해당 폴더에 매핑된 색상을 반환합니다.
    파일이 루트에 있으면 "root" 색상을 반환합니다.
    """
    parts = note_rel_path.split("/")
    key = parts[0] if parts[0] else "root"
    return FOLDER_COLOR_MAP.get(key, "#355c7d")  # 기본값

def write_markdown_nodes(project_root: Path, vault_root: Path):
    """
    프로젝트 내의 각 파이썬 파일을 분석하여, Obsidian 노드(마크다운 파일)를 생성합니다.
    - 파일명이 "__"로 시작하는 파일은 제외합니다.
    - 노드 상단에 YAML frontmatter를 추가하여, 경로에 따른 색상을 지정합니다.
    - 파일 내 import 구문에 따라 내부 모듈은 내부 링크(노드)로, 그 외는 외부 의존성으로 기록합니다.
    
    출력은 vault_root 내에, 프로젝트 내 상대 경로 구조를 그대로 반영하여 생성됩니다.
    """
    internal_modules = get_internal_modules(project_root)
    for filepath in project_root.rglob("*.py"):
        if ".venv" in filepath.parts:
            continue
        if filepath.name.startswith("__"):
            continue  # __로 시작하는 파일은 스킵
        
        rel_path = filepath.relative_to(project_root)
        # 모듈명 생성 (확장자 제거)
        if filepath.name == "__init__.py":
            mod_name = rel_path.parent.as_posix().replace("/", ".")
        else:
            mod_name = rel_path.with_suffix("").as_posix().replace("/", ".")
        
        # 노드 파일의 relative 경로 (마크다운 파일로 저장, 확장자 .md)
        note_rel_path = rel_path.with_suffix(".md").as_posix()
        note_full_path = vault_root / note_rel_path
        note_full_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 노드 색상 결정 (상대 경로에서 최상위 폴더 기준)
        node_color = get_color_for_node(note_rel_path)
        
        # import 구문 분석
        internal_deps, external_deps = parse_imports(filepath, internal_modules)
        
        lines = []
        # YAML frontmatter에 color 속성 추가
        lines.append("---")
        lines.append(f"color: \"{node_color}\"")
        lines.append("---")
        lines.append("")
        # 제목: 파일 경로
        lines.append(f"# {rel_path.as_posix()}")
        lines.append("")
        
        if internal_deps:
            lines.append("## Internal Dependencies")
            for dep in sorted(internal_deps):
                # internal_modules[dep]는 해당 노드의 relative note path (확장자 없이)
                link = internal_modules.get(dep, dep)
                lines.append(f"- [[{link}]]")
            lines.append("")
        
        if external_deps:
            lines.append("## External Dependencies")
            for dep in sorted(external_deps):
                lines.append(f"- {dep}")
            lines.append("")
        
        content = "\n".join(lines)
        note_full_path.write_text(content, encoding="utf-8")
        print(f"Generated node: {note_full_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="프로젝트 루트의 각 파이썬 파일을 Obsidian 노드(마크다운 파일)로 생성하고, import 관계를 내부 링크로 연결합니다.\n"
                    "내부 모듈은 노드로 생성하며, 파일명이 '__'로 시작하는 파일은 제외합니다.\n"
                    "또한, 노드 상단에 YAML frontmatter로 경로별 색상을 지정합니다."
    )
    parser.add_argument("project_root", help="프로젝트 루트 디렉토리 경로")
    parser.add_argument("vault_path", help="Obsidian Vault 저장 경로")
    args = parser.parse_args()
    
    project_root = Path(args.project_root).resolve()
    vault_root = Path(args.vault_path).resolve()
    
    if not project_root.is_dir():
        raise SystemExit(f"프로젝트 경로를 찾을 수 없습니다: {project_root}")
    if not vault_root.is_dir():
        raise SystemExit(f"Vault 경로를 찾을 수 없습니다: {vault_root}")
    
    write_markdown_nodes(project_root, vault_root)