.PHONY: dev run watch lint format dev-icons pot update-po mo flatpak flatpak-bundle flatpak-run rpm deb appimage clear-auth clean

dev:
	uv venv --python /usr/bin/python3 --system-site-packages --clear
	uv sync
	$(MAKE) mo

run: mo
	uv run gnusteampacker

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

clear-auth:
	uv run python scripts/cleaner.py

clean:
	rm -rf build-dir .flatpak-builder flatpak-repo requirements.txt __pycache__ gnusteampacker/__pycache__ gnusteampacker/ui/__pycache__ gnusteampacker/locale
