.PHONY: dev run run-debug watch lint format dev-icons pot update-po mo flatpak flatpak-bundle flatpak-run dist-cli dist-gui rpm deb install appimage daemon-dev-install clear-auth clean

PYVER := $(shell python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')

# Package installed by `make install` (full = CLI + GUI). Override with e.g. `make install INSTALL_PACKAGE=gnusteampacker`.
INSTALL_PACKAGE ?= gnusteampacker-full
# Privilege-elevation prefix used when not running as root. Override with `make install SUDO=` if unwanted.
SUDO ?= sudo

dev:
	uv venv --python /usr/bin/python3 --system-site-packages --clear
	uv sync
	$(MAKE) mo

run: mo
	uv run gnusteampacker

run-debug: mo
	GNUSTEAMPACKER_DEBUG=1 uv run gnusteampacker

watch:
	uv run watchfiles --filter python "python -m gnusteampacker.main" gnusteampacker

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

pot:
	find gnusteampacker -name '*.py' | sort > /tmp/gsp-potfiles.txt
	xgettext --from-code=UTF-8 --language=Python --keyword=_ --add-comments \
		--package-name=GnuSteamPacker --package-version=0.1.0 \
		--copyright-holder="SavageCore" \
		--msgid-bugs-address="https://github.com/SavageCore/GnuSteamPacker/issues" \
		--output=po/gnusteampacker.pot --files-from=/tmp/gsp-potfiles.txt
	rm -f /tmp/gsp-potfiles.txt

update-po: pot
	for po in po/*.po; do \
		msgmerge --update --backup=off "$$po" po/gnusteampacker.pot; \
	done

mo:
	for lang in $$(cat po/LINGUAS); do \
		install -d "gnusteampacker/locale/$$lang/LC_MESSAGES"; \
		msgfmt -o "gnusteampacker/locale/$$lang/LC_MESSAGES/gnusteampacker.mo" "po/$$lang.po"; \
	done

flatpak:
	flatpak-builder --force-clean --repo=flatpak-repo build-dir org.gnusteampacker.GnuSteamPacker.json

flatpak-bundle: flatpak
	flatpak build-bundle flatpak-repo gnusteampacker.flatpak org.gnusteampacker.GnuSteamPacker

flatpak-run:
	flatpak-builder --run build-dir org.gnusteampacker.GnuSteamPacker.json gnusteampacker

dist-cli: mo
	meson setup build-cli -Dgui=false --prefix=/usr --wipe
	meson install -C build-cli --destdir $(CURDIR)/dist-cli
	python3 -m pip install blake3 --no-deps --quiet --target $(CURDIR)/dist-cli/usr/lib/python$(PYVER)/site-packages/

dist-gui: mo
	meson setup build-gui -Dgui=true --prefix=/usr --wipe
	meson install -C build-gui --destdir $(CURDIR)/dist-gui
	python3 -m pip install blake3 --no-deps --quiet --target $(CURDIR)/dist-gui/usr/lib/python$(PYVER)/site-packages/

rpm: dist-cli dist-gui
	mkdir -p dist-packages
	nfpm package --packager rpm --target dist-packages/ --config nfpm.yml
	PYVER=$(PYVER) envsubst '$$PYVER' < nfpm-gui.yml | PYVER=$(PYVER) nfpm package --packager rpm --target dist-packages/ --config /dev/stdin
	nfpm package --packager rpm --target dist-packages/ --config nfpm-combined.yml

deb: dist-cli dist-gui
	mkdir -p dist-packages
	nfpm package --packager deb --target dist-packages/ --config nfpm.yml
	PYVER=$(PYVER) envsubst '$$PYVER' < nfpm-gui.yml | PYVER=$(PYVER) nfpm package --packager deb --target dist-packages/ --config /dev/stdin
	nfpm package --packager deb --target dist-packages/ --config nfpm-combined.yml

# Build the packages and install the combined (CLI + GUI) one via the distro's package manager,
# so dependencies are resolved and upgrades tracked by dnf/apt. Runs through sudo unless already root.
install: rpm
	@set -e; \
	if command -v dnf >/dev/null 2>&1; then \
		pkg="$$(ls dist-packages/$(INSTALL_PACKAGE)-*.rpm | head -n1)"; \
		if rpm -q "$(INSTALL_PACKAGE)" >/dev/null 2>&1; then \
			inst="dnf reinstall -y $$pkg"; \
		else \
			inst="dnf install -y $$pkg"; \
		fi; \
	elif command -v apt-get >/dev/null 2>&1; then \
		pkg="$$(ls dist-packages/$(INSTALL_PACKAGE)-*.deb | head -n1)"; \
		inst="dpkg --force-reinstall -i $$pkg && apt-get install -f -y"; \
	else \
		echo "Error: no supported package manager (dnf/apt-get). Install dist-packages/$(INSTALL_PACKAGE)-* manually."; \
		exit 1; \
	fi; \
	echo "Installing: $$pkg"; \
	if [ "$$(id -u)" -eq 0 ]; then \
		sh -c "$$inst"; \
	else \
		$(SUDO) sh -c "$$inst"; \
	fi

appimage:
	uv export --no-dev --no-hashes --no-annotate -o requirements.txt
	sed -i '/^-e \./d; s/ ;.*//' requirements.txt
	python-appimage build app -p 3.11 .

daemon-dev-install:
	cp data/gnusteampacker-daemon.service ~/.config/systemd/user/
	cp data/gnusteampacker-daemon.timer ~/.config/systemd/user/
	mkdir -p ~/.config/systemd/user/gnusteampacker-daemon.service.d
	printf '[Service]\nExecStart=\nExecStart=%s/.venv/bin/python -m gnusteampacker.main daemon check\nWorkingDirectory=%s\n' \
		$(CURDIR) $(CURDIR) > ~/.config/systemd/user/gnusteampacker-daemon.service.d/dev-override.conf
	systemctl --user daemon-reload
	@echo "Daemon units installed. Enable with: systemctl --user enable --now gnusteampacker-daemon.timer"

clear-auth:
	uv run python scripts/cleaner.py

clean:
	rm -rf build-dir build-cli build-gui dist-cli dist-gui dist-packages .flatpak-builder flatpak-repo requirements.txt __pycache__ gnusteampacker/__pycache__ gnusteampacker/ui/__pycache__ gnusteampacker/locale
