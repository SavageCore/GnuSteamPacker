.PHONY: dev run watch lint format flatpak rpm deb appimage clean

dev:
	uv venv --python /usr/bin/python3 --system-site-packages --clear
	uv sync

run:
	uv run gnusteampacker

watch:
	find gnusteampacker -name '*.py' | entr -r uv run gnusteampacker

lint:
	uv run ruff check gnusteampacker/

format:
	uv run ruff format gnusteampacker/

flatpak:
	flatpak-builder --force-clean build-dir org.gnusteampacker.GnuSteamPacker.json

flatpak-run:
	flatpak-builder --run build-dir org.gnusteampacker.GnuSteamPacker.json gnusteampacker

rpm:
	uv export --no-dev -o /tmp/gsp-requirements.txt
	nfpm package --packager rpm --config nfpm.yml

deb:
	uv export --no-dev -o /tmp/gsp-requirements.txt
	nfpm package --packager deb --config nfpm.yml

requirements.txt:
	uv export --no-dev -o requirements.txt

appimage: requirements.txt
	python-appimage build app -p 3.11 .

clean:
	rm -rf build-dir .flatpak-builder __pycache__ gnusteampacker/__pycache__ gnusteampacker/ui/__pycache__
