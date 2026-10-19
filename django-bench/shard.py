"""Print the Django test modules that belong to one shard.

Usage: python shard.py <django_dir> <shard_index starting at 1> <shard_count>

Lists test modules the same way Django's tests/runtests.py does with GIS
disabled (top-level packages under tests/, minus the ones runtests skips),
sorts them, and deals them out round-robin. Round-robin by module is simple
and identical on every platform; it is not balanced by duration, so the
slowest shard sets the time, as boxd's page also notes.
"""

import os
import sys

# Mirrors SUBDIRS_TO_SKIP[""] in tests/runtests.py, plus gis_tests because
# GIS is disabled when GDAL is not installed (true on every runner here).
SKIP = {"import_error_package", "playwright_tests", "test_runner_apps", "gis_tests"}


def test_modules(django_dir: str) -> list[str]:
    tests_dir = os.path.join(django_dir, "tests")
    modules = []
    for entry in os.scandir(tests_dir):
        if (
            "." in entry.name
            or entry.name in SKIP
            or entry.is_file()
            or not os.path.exists(os.path.join(entry.path, "__init__.py"))
        ):
            continue
        modules.append(entry.name)
    return sorted(modules)


def main() -> None:
    django_dir, index, count = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    if not 1 <= index <= count:
        sys.exit(f"shard index {index} is outside 1..{count}")
    # Shard i takes modules i-1, i-1+count, i-1+2*count, ...
    print(" ".join(test_modules(django_dir)[index - 1 :: count]))


if __name__ == "__main__":
    main()
