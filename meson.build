project('gnusteampacker',
  version: '0.1.0',
  meson_version: '>= 1.0',
)

py = import('python').find_installation('python3')
gnome = import('gnome')

install_subdir('gnusteampacker', install_dir: py.get_install_dir())

install_data(
  'data/org.gnusteampacker.GnuSteamPacker.desktop',
  install_dir: get_option('datadir') / 'applications',
)

install_data(
  'data/icons/hicolor/scalable/apps/org.gnusteampacker.GnuSteamPacker.svg',
  install_dir: get_option('datadir') / 'icons/hicolor/scalable/apps',
)

gnome.post_install(
  glib_compile_schemas: true,
  gtk_update_icon_cache: true,
  update_desktop_database: true,
)
