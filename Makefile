###################################################################################################
#
#    MODEL-COMPRESSER -- Make 3D cave models smaller for sharing
#
#    Copyright (C) 2026 by Jari Arkko -- See LICENSE for license information.
#
###################################################################################################

PROGRAM	=	model-compresser
TESTS	=	test/run-tests.py
BLENDER	=	blender-decimate.py
UV	=	uv

.PHONY: all test clean distclean wc

# The program is a Python script whose dependencies (numpy, pymeshlab, trimesh,
# pillow) are declared inline in the script itself (PEP 723). "uv run" -- which
# the script's #! line invokes -- installs them into uv's cache the first time
# the program is run. "make" just does that installation ahead of time, and
# checks that the program starts.

all:
	@command -v $(UV) >/dev/null 2>&1 || \
		{ echo "$(PROGRAM): uv is required to run this program (brew install uv), see README.md"; exit 1; }
	$(UV) sync --script $(PROGRAM)
	./$(PROGRAM) --version

test: all
	$(UV) run --script $(TESTS)

clean:
	rm -rf test/output __pycache__ test/__pycache__

distclean: clean

wc:
	wc $(PROGRAM) $(TESTS) $(BLENDER)
