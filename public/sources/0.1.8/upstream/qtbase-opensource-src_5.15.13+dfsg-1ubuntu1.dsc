-----BEGIN PGP SIGNED MESSAGE-----
Hash: SHA512

Format: 3.0 (quilt)
Source: qtbase-opensource-src
Binary: libqt5core5t64, libqt5gui5t64, qt5-gtk-platformtheme, qt5-xdgdesktopportal-platformtheme, libqt5network5t64, libqt5opengl5t64, libqt5sql5t64, libqt5sql5-mysql, libqt5sql5-odbc, libqt5sql5-psql, libqt5sql5-sqlite, libqt5sql5-tds, libqt5sql5-ibase, libqt5xml5t64, libqt5dbus5t64, libqt5test5t64, libqt5concurrent5t64, libqt5widgets5t64, libqt5printsupport5t64, qtbase5-dev, qtbase5-private-dev, libqt5opengl5-dev, qtbase5-dev-tools, qt5-qmake-bin, qt5-qmake, qtbase5-examples, qtbase5-doc, qtbase5-doc-html, qtbase5-doc-dev
Architecture: any all
Version: 5.15.13+dfsg-1ubuntu1
Maintainer: Ubuntu Developers <ubuntu-devel-discuss@lists.ubuntu.com>
Uploaders: Sune Vuorela <sune@debian.org>, Pino Toscano <pino@debian.org>, Lisandro Damián Nicanor Pérez Meyer <lisandro@debian.org>, Timo Jyrinki <timo@debian.org>, Dmitry Shachnev <mitya57@debian.org>, Simon Quigley <tsimonq2@debian.org>
Homepage: https://www.qt.io/developers/
Standards-Version: 4.6.2
Vcs-Browser: https://salsa.debian.org/qt-kde-team/qt/qtbase
Vcs-Git: https://salsa.debian.org/qt-kde-team/qt/qtbase.git
Build-Depends: debhelper-compat (= 13), default-libmysqlclient-dev, dh-exec, dpkg-dev (>= 1.22.5), firebird-dev [linux-any], freetds-dev, libasound2-dev [linux-any], libatspi2.0-dev, libcups2-dev, libdbus-1-dev, libdouble-conversion-dev, libdrm-dev [linux-any], libfontconfig-dev, libfreetype-dev, libgbm-dev [linux-any], libgl-dev, libgles-dev, libglib2.0-dev, libglu1-mesa-dev | libglu-dev, libgtk-3-dev, libharfbuzz-dev, libicu-dev, libinput-dev [linux-any], libjpeg-dev, libkrb5-dev, libmd4c-dev, libmtdev-dev [linux-any], libpcre2-dev, libpng-dev, libpq-dev, libproxy-dev, libpulse-dev, libsqlite3-dev, libssl-dev, libudev-dev [linux-any], libvulkan-dev [linux-any], libx11-dev, libx11-xcb-dev, libxcb-glx0-dev, libxcb-icccm4-dev, libxcb-image0-dev, libxcb-keysyms1-dev, libxcb-randr0-dev, libxcb-render-util0-dev, libxcb-render0-dev, libxcb-shape0-dev, libxcb-shm0-dev, libxcb-sync-dev, libxcb-util-dev, libxcb-xfixes0-dev, libxcb-xinerama0-dev, libxcb-xinput-dev, libxcb-xkb-dev, libxcb1-dev, libxext-dev, libxi-dev, libxkbcommon-dev, libxkbcommon-x11-dev, libxrender-dev, libzstd-dev, pkg-kde-tools, pkgconf, publicsuffix, qt5-qmake-bin <cross>, unixodbc-dev, zlib1g-dev
Build-Depends-Indep: qdoc-qt5 (>= 5.15~) <!nodoc>, qhelpgenerator-qt5 (>= 5.15~) <!nodoc>, qtattributionsscanner-qt5 <!nodoc>
Package-List:
 libqt5concurrent5t64 deb libs optional arch=any
 libqt5core5t64 deb libs optional arch=any
 libqt5dbus5t64 deb libs optional arch=any
 libqt5gui5t64 deb libs optional arch=any
 libqt5network5t64 deb libs optional arch=any
 libqt5opengl5-dev deb libdevel optional arch=any
 libqt5opengl5t64 deb libs optional arch=any
 libqt5printsupport5t64 deb libs optional arch=any
 libqt5sql5-ibase deb libs optional arch=linux-any
 libqt5sql5-mysql deb libs optional arch=any
 libqt5sql5-odbc deb libs optional arch=any
 libqt5sql5-psql deb libs optional arch=any
 libqt5sql5-sqlite deb libs optional arch=any
 libqt5sql5-tds deb libs optional arch=any
 libqt5sql5t64 deb libs optional arch=any
 libqt5test5t64 deb libs optional arch=any
 libqt5widgets5t64 deb libs optional arch=any
 libqt5xml5t64 deb libs optional arch=any
 qt5-gtk-platformtheme deb libs optional arch=any
 qt5-qmake deb devel optional arch=any
 qt5-qmake-bin deb devel optional arch=any
 qt5-xdgdesktopportal-platformtheme deb libs optional arch=any
 qtbase5-dev deb libdevel optional arch=any
 qtbase5-dev-tools deb devel optional arch=any
 qtbase5-doc deb doc optional arch=all profile=!nodoc
 qtbase5-doc-dev deb libdevel optional arch=all profile=!nodoc
 qtbase5-doc-html deb doc optional arch=all profile=!nodoc
 qtbase5-examples deb x11 optional arch=any
 qtbase5-private-dev deb libdevel optional arch=any
Checksums-Sha1:
 f51f8ac10bdc78b9c8535dc543a3afd3b394f6ff 48578972 qtbase-opensource-src_5.15.13+dfsg.orig.tar.xz
 0c067aae944f086ff3e7a7c8eb1189060c54056c 231916 qtbase-opensource-src_5.15.13+dfsg-1ubuntu1.debian.tar.xz
Checksums-Sha256:
 397493b55747a54718a80a9e72222bac92b069e2f463f1509a85de02563c964d 48578972 qtbase-opensource-src_5.15.13+dfsg.orig.tar.xz
 5a40418b9398a01967609e5f4b3b4410122ae679e273c6fe319dffebda5b38f4 231916 qtbase-opensource-src_5.15.13+dfsg-1ubuntu1.debian.tar.xz
Files:
 ddd2394e8bd8e5c2f9b444f94d02924a 48578972 qtbase-opensource-src_5.15.13+dfsg.orig.tar.xz
 cf1ab599ce0b90aed08b54e3cb102722 231916 qtbase-opensource-src_5.15.13+dfsg-1ubuntu1.debian.tar.xz
Original-Maintainer: Debian Qt/KDE Maintainers <debian-qt-kde@lists.debian.org>

-----BEGIN PGP SIGNATURE-----

iQJHBAEBCgAxFiEEq2sdvrA0LydXHe1qsmYUtFL0RrYFAmYGrKQTHG1pdHlhNTdA
ZGViaWFuLm9yZwAKCRCyZhS0UvRGtvovEACuVi9Iafbti7yuh2OuSTTuVY7i77gM
7CDWxLwRZWvos6F17hOTJA3/EcZzPVFmon8GoyqzzY4tH5nLPrt5RIk9e8kaClHb
U3/jhAR/lKKZPhbId7IGUYclVkFPKpw3/HfZ6u/tgf4hDigM+W6Q7v5WLXkqCkbv
1nFpFnVBT50Xc+/wjhDoKMradmIOnwvazWf1a1H+VU8/wGaUlaRhr8WkP4xc++kw
ZK0V5KRl3vKxyDdHVOTmW2kkh03qRB913qVETTlt4x3VR7fLU8S+8EB+X5BDAvaL
UjX/n/T1khi6Yg//LwZOf9XIOcU4FwiTXMD4jvDAj6GJ+j0qTWCQgscBTb8w26cy
z0wxPewZ/7n7YiUqPGe2fLqvGMoN3XvtJXAH5FkIliKtnJNn8VuvLkFj2Z6sDpUs
cJd8eFR7W9odBG/bJM3xXOsv38nl90uQ0Rp7Z0KAZK9x2YPdtZ8/HDvs0KpvJkA8
6/3vAm0XQLXyXT/QsD9CmFpBEh9UPrEA0cBVOBXtcdvVIY9FqJsO2wzxFzRCAQzD
0LvlGB85S6RYpJb0rAco/W08tqjbPhhEgl9CH0VczNaTNRjRNRt96DLoXpMwJfNV
mn+3pN74KVEhPLZfj1UJLA5o9NGsOINs6FFZoy6cX6S8EPwmpmA0BpShQisvM9by
go7sYBJ1L6TFSQ==
=d4z8
-----END PGP SIGNATURE-----
