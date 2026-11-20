<div align="center">

<img src="https://raw.githubusercontent.com/elfenomenokim/atomic-write/main/docs/logo.svg" width="96" height="96" alt="체크 표시가 있는 파일 아이콘">

# atomic-write

파일을 온전한 바이트로 교체하거나, 이전 바이트를 그대로 두는 Python 라이브러리입니다.

[English](README.md) · Python 3.9+ · 의존성 없음

[![pypi](https://img.shields.io/pypi/v/feno-atomic-write?label=pypi)](https://pypi.org/project/feno-atomic-write/)
[![tests](https://github.com/elfenomenokim/atomic-write/actions/workflows/tests.yml/badge.svg)](https://github.com/elfenomenokim/atomic-write/actions/workflows/tests.yml)
[![license](https://img.shields.io/github/license/elfenomenokim/atomic-write)](https://github.com/elfenomenokim/atomic-write/blob/main/LICENSE)

[설치](#설치) · [빠른 시작](#빠른-시작) · [레퍼런스](#레퍼런스)

</div>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/elfenomenokim/atomic-write/main/docs/diagrams/write-path.ko.dark.svg">
    <img src="https://raw.githubusercontent.com/elfenomenokim/atomic-write/main/docs/diagrams/write-path.ko.light.svg" width="640" alt="쓰기는 대상 옆에 배타적 임시 파일을 만들고, 최종 모드를 지정하고, 쓰기와 fsync를 한 뒤 대상 위로 이름을 바꿉니다. 실패하면 임시 파일을 지우고 이전 바이트를 남깁니다.">
  </picture>
</p>

## 왜 필요한가

`os.replace`는 이름 변경만 원자적입니다. 임시 파일 생성, flush, fsync, 권한 유지,
create-only, 디렉터리 sync는 직접 만들어야 합니다. 상태 파일을 쓰는 프로젝트마다
이 조립이 조금씩 다릅니다. 어떤 곳은 임시 파일을 만든 뒤에 chmod하고, 어떤 곳은
디렉터리를 fsync하지 않고, 어떤 곳은 프로세스 id만으로 임시 이름을 만듭니다.

가장 알려진 전용 라이브러리인
[python-atomicwrites](https://github.com/untitaker/python-atomicwrites)는
2022년 7월에 아카이브되었습니다. `overwrite` 플래그로 경쟁에 안전한 create-only를
제공하지만 디렉터리 fsync나 `dir_fd` 제어는 문서화되어 있지 않습니다. 이 라이브러리는
그 두 계약만 명시하고 나머지는 만들지 않습니다.

| | `os.replace` | python-atomicwrites | atomic-write |
|---|---|---|---|
| 같은 디렉터리 임시 파일 | 직접 구현 | 지원 | 지원 |
| 디렉터리 fsync | 없음 | 문서화 안 됨 | `file+directory` (기본값) |
| 경쟁에 안전한 create-only | 없음 | `overwrite=False` | `overwrite=False` |
| 기존 권한 유지 | 없음 | 문서화 안 됨 | 기본값 |
| `dir_fd` 격리 | 직접 구현 | 없음 | `dir_fd=` |
| 유지보수 | 표준 라이브러리 | 2022년 아카이브 | 이 저장소 |

## 설치

```sh
pip install feno-atomic-write
```

PyPI 이름은 `feno-atomic-write`입니다. `atomic-write`는 기존 프로젝트와 너무 비슷해 쓸 수 없었고, import 이름은 그대로 `atomic_write`입니다.

체크아웃에서 설치할 수도 있습니다.

```sh
python3 -m pip install .
```

## 빠른 시작

빈 폴더에서 실제로 돌린 결과입니다. 권한을 유지하며 파일을 교체하고, 두 번째 쓰기가 가져갈 수 없는 선점 파일을 만듭니다.

```python
import os, stat
from atomic_write import write_json, write_text

write_json("state.json", {"plan": "pro", "remaining": 42})
print(open("state.json").read(), end="")

os.chmod("state.json", 0o600)
write_json("state.json", {"plan": "pro", "remaining": 41})
print(oct(stat.S_IMODE(os.stat("state.json").st_mode)))

write_text("owner.lock", "4242", overwrite=False)
try:
    write_text("owner.lock", "5151", overwrite=False)
except FileExistsError as error:
    print("FileExistsError:", error.filename)
print(open("owner.lock").read())
print(sorted(os.listdir(".")))
```

```text
{
  "plan": "pro",
  "remaining": 42
}
0o600
FileExistsError: owner.lock
4242
['owner.lock', 'state.json']
```

파일을 교체하면서 권한을 유지합니다.

```python
from atomic_write import write_text

write_text("~/.config/app/token", "abc123")
```

다른 프로세스의 파일을 덮어쓰지 않는 선점 파일을 만듭니다.

```python
from atomic_write import write_json
from pathlib import Path

write_json(Path("run/owner.json"), {"pid": 4242}, overwrite=False)
# 이미 있으면 FileExistsError가 납니다.
```

이미 검증한 디렉터리 안에서 씁니다.

```python
import os
from atomic_write import write_bytes

directory = os.open(state_dir, os.O_RDONLY)
try:
    write_bytes("cursor.bin", b"\x00\x01", dir_fd=directory)
finally:
    os.close(directory)
```

파일이 사라져도 괜찮은 캐시에는 fsync를 생략합니다.

```python
from atomic_write import write_json

write_json("cache/quota.json", cache, durability="none")
```

## 레퍼런스

### `write_text(path, text, *, encoding="utf-8", errors=None, newline=None, mode=None, overwrite=True, durability="file+directory", dir_fd=None, follow_symlinks=True) -> int`

`text`를 쓰고 쓴 글자 수를 돌려줍니다.

### `write_bytes(path, data, *, mode=None, overwrite=True, durability="file+directory", dir_fd=None, follow_symlinks=True) -> int`

`bytes`, `bytearray`, `memoryview`를 받고 쓴 바이트 수를 돌려줍니다.

### `write_json(path, value, **kwargs) -> int`

파일을 만지기 전에 `json.dumps`로 직렬화합니다. 그래서 인코딩할 수 없는 값은
파일을 건드리지 않습니다. `indent`(기본 2), `sort_keys`(기본 `False`),
`ensure_ascii`(기본 `False`), `allow_nan`(기본 `True`),
`separators`(기본은 표준 라이브러리 기본값), `default`(`json.dumps`와 같음),
`newline`(기본 `"\n"`, 없애려면 `None`)을 받습니다.
나머지 인자는 `write_text`로 넘어갑니다.

### `atomic_path(path, **kwargs)`

블록이 정상 종료하면 파일을 교체하고, 예외가 나면 버리는 컨텍스트 매니저입니다.

```python
from atomic_write import atomic_path

with atomic_path("report.md") as staged:
    for row in rows:
        staged.write(row + "\n")
# 반복이 끝났을 때만 report.md가 교체됩니다.
```

`binary=True`를 주면 바이트 스트림을 받습니다. 조각 복사, zip 파일, 업로드에 씁니다.
`staged.path`는 임시 파일 이름이고, `staged.sync()`는 임시 파일을 flush·fsync합니다.
그래서 게시하기 전에 쓴 내용이나 대상 파일이 그대로인지 확인할 수 있습니다.
블록 안에서 `staged.discard()`를 부르면 게시하지 않고 이전 파일을 남깁니다.

```python
import shutil, zipfile

with open(source, "rb") as src, atomic_path(target, binary=True, mode=0o600) as staged:
    shutil.copyfileobj(src, staged)
    staged.sync()
    if not zipfile.is_zipfile(staged.path):
        staged.discard()  # target은 이전 바이트를 유지합니다
```

### 계약

| 인자 | 값 | 의미 |
|---|---|---|
| `overwrite` | `True` (기본) | 기존 파일을 교체합니다 |
| | `False` | 새 파일로만 게시하고, 있으면 `FileExistsError`입니다. `os.link`를 쓰므로 동시에 만든 둘 중 하나만 성공합니다 |
| `durability` | `none` | fsync 없음. 크래시로 새 파일을 잃을 수 있습니다 |
| | `file` | 이름 변경 전에 새 바이트를 fsync합니다 |
| | `file+directory` (기본) | 디렉터리까지 fsync해서 이름 변경이 크래시를 견딥니다 |
| | `full` | `file+directory`에 더해 macOS `F_FULLFSYNC`로 드라이브 캐시가 아닌 저장 매체까지 기록합니다 |
| `mode` | `int` 또는 `None` | `None`이면 기존 파일 권한을 유지하고, 새 파일은 umask를 뺀 `0o666`입니다 |
| | `"umask"` | 기존 권한과 상관없이 매번 umask를 뺀 `0o666`을 씁니다. 평범한 `open(path, "w")`와 같습니다 |
| `dir_fd` | `int` 또는 `None` | 열어 둔 디렉터리 디스크립터 기준으로 쓰고, 이름 변경도 같은 디스크립터로 합니다 |
| `follow_symlinks` | `True` (기본) | 링크의 대상 파일을 교체하고 링크는 남깁니다 |
| | `False` | 링크 자체를 교체합니다 |

쓰기가 실패하면 일부 바이트가 게시되지 않습니다. 대상 파일은 이전 내용을 그대로
가지고, 임시 파일은 지워집니다. 직렬화는 파일을 만지기 전에 끝납니다.

같은 경로에 쓰는 두 작성자는 임시 이름을 공유하지 않습니다. 그래서 중첩되거나
동시에 일어난 쓰기가 다른 작성자가 채우고 있는 파일을 게시할 수 없습니다.
임시 파일은 프로세스의 작업 폴더와 상관없이 항상 대상 옆에 만듭니다(launchd 작업은
작업 폴더가 `/`입니다).

디렉터리를 fsync할 수 없는 파일 시스템(SMB, FUSE의 `EINVAL`·`ENOTSUP`)에서는 디렉터리
fsync를 건너뜁니다. 그 시점에는 이미 이름 변경이 끝났기 때문입니다.

## 플랫폼

- 테스트는 macOS arm64(CPython 3.12), Ubuntu 24.04 arm64(CPython 3.12), Windows 11
  (CPython 3.10)에서 모두 통과합니다.
- Windows에는 POSIX 권한 비트와 `dir_fd`가 없고 디렉터리 fsync도 할 수 없습니다.
  그래서 `mode`는 읽기 전용 여부만 바꾸고, 디렉터리 동기화는 생략하며, 해당 기능
  테스트는 Windows에서 건너뜁니다.
- Windows는 다른 프로세스가 열어 둔 파일을 교체하지 못합니다. 이때 약 1초 동안
  교체를 다시 시도한 뒤에도 안 되면 `PermissionError`를 냅니다.
- `write_text`는 Python 텍스트 모드를 쓰므로 Windows에서 `newline=None`이면 `open()`처럼
  `\r\n`을 씁니다. 모든 플랫폼에서 같은 바이트가 필요하면 `newline="\n"`을 넘기세요.
- `dir_fd`는 격리 도구이지 샌드박스가 아닙니다. `..`이 들어간 이름은 커널이 그대로
  해석합니다. 이름은 넘기기 전에 검증하세요.

## 한계

- 파일 하나를 씁니다. 디렉터리 트리, 매니페스트와 그 구성원, 여러 파일 트랜잭션은
  다루지 않습니다.
- 잠그지 않습니다. 읽고-고쳐-쓰는 주기가 필요하면 호출하는 쪽이 잠금을 소유합니다.
- 상위 디렉터리를 만들지 않습니다. 없으면 `FileNotFoundError`가 납니다.
- 쓴 바이트를 다시 읽어 검증하지 않습니다. `atomic_path`와 `staged.sync()`로
  호출하는 쪽이 게시 전에 확인할 수 있습니다.

## 기여

[CONTRIBUTING.md](CONTRIBUTING.md)를 보세요. 테스트는 이렇게 실행합니다.

```sh
python3 -m pytest tests -q
```

## 라이선스

[MIT](LICENSE).
