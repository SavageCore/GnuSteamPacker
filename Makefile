.PHONY: dev run watch lint format dev-icons flatpak rpm deb appimage clean

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

dev-icons:
	install -Dm644 data/icons/hicolor/scalable/apps/org.gnusteampacker.GnuSteamPacker.svg \
		$(HOME)/.local/share/icons/hicolor/scalable/apps/org.gnusteampacker.GnuSteamPacker.svg
	install -Dm644 data/org.gnusteampacker.GnuSteamPacker.desktop \
		$(HOME)/.local/share/applications/org.gnusteampacker.GnuSteamPacker.desktop
	gtk-update-icon-cache -f -t $(HOME)/.local/share/icons/hicolor/ 2>/dev/null || true
	update-desktop-database $(HOME)/.local/share/applications/ 2>/dev/null || true
	@echo "Icon installed. Restart the shell or re-login if icon is still missing."

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

appimage:
	uv export --no-dev --no-hashes --no-annotate -o requirements.txt
	sed -i '/^-e \./d; s/ ;.*//' requirements.txt
	python-appimage build app -p 3.11 .

clean:
	rm -rf build-dir .flatpak-builder requirements.txt __pycache__ gnusteampacker/__pycache__ gnusteampacker/ui/__pycache__
