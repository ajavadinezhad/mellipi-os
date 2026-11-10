-----BEGIN PGP SIGNED MESSAGE-----
Hash: SHA512

Format: 3.0 (quilt)
Source: qtwayland-opensource-src
Binary: qtwayland5-examples, libqt5waylandclient5, libqt5waylandcompositor5, qml-module-qtwayland-compositor, qml-module-qtwayland-client-texturesharing, libqt5waylandcompositor5-dev, libqt5waylandclient5-dev, qtwayland5-private-dev, qtwayland5-dev-tools, qtwayland5, qtwayland5-doc, qtwayland5-doc-html
Architecture: any all
Version: 5.15.13-1
Maintainer: Debian Qt/KDE Maintainers <debian-qt-kde@lists.debian.org>
Uploaders: Dmitry Shachnev <mitya57@debian.org>, Lisandro Damián Nicanor Pérez Meyer <lisandro@debian.org>, Sune Vuorela <debian@pusling.com>, Pino Toscano <pino@debian.org>, Timo Jyrinki <timo@debian.org>, Simon Quigley <tsimonq2@debian.org>, Patrick Franz <deltaone@debian.org>
Homepage: https://doc.qt.io/qt-5/wayland-and-qt.html
Standards-Version: 4.6.2
Vcs-Browser: https://salsa.debian.org/qt-kde-team/qt/qtwayland
Vcs-Git: https://salsa.debian.org/qt-kde-team/qt/qtwayland.git
Build-Depends: dbus <!nocheck>, debhelper-compat (= 13), dpkg-dev (>= 1.17.14), libegl1-mesa-dev, libfontconfig-dev, libglib2.0-dev, libinput-dev, libmtdev-dev [linux-any], libudev-dev [linux-any], libwayland-dev (>= 1.8.0), libwayland-egl1-mesa | libwayland-egl1, libxcomposite-dev, libxkbcommon-dev (>= 0.2.0), libxrender-dev, pkg-kde-tools, pkgconf, qtbase5-dev (>= 5.15.13+dfsg~), qtbase5-dev:native (>= 5.15.13+dfsg~), qtbase5-private-dev (>= 5.15.13+dfsg~), qtdeclarative5-private-dev (>= 5.15.13+dfsg~), xauth <!nocheck>, xvfb <!nocheck>
Build-Depends-Indep: qdoc-qt5 (>= 5.15.13~) <!nodoc>, qhelpgenerator-qt5 (>= 5.15.13~) <!nodoc>, qtattributionsscanner-qt5 (>= 5.15.13~) <!nodoc>, qtbase5-doc-html (>= 5.15.13+dfsg~) <!nodoc>
Package-List:
 libqt5waylandclient5 deb libs optional arch=any
 libqt5waylandclient5-dev deb libdevel optional arch=any
 libqt5waylandcompositor5 deb libs optional arch=any
 libqt5waylandcompositor5-dev deb libdevel optional arch=any
 qml-module-qtwayland-client-texturesharing deb libs optional arch=any
 qml-module-qtwayland-compositor deb libs optional arch=any
 qtwayland5 deb libs optional arch=any
 qtwayland5-dev-tools deb devel optional arch=any
 qtwayland5-doc deb doc optional arch=all profile=!nodoc
 qtwayland5-doc-html deb doc optional arch=all profile=!nodoc
 qtwayland5-examples deb x11 optional arch=any
 qtwayland5-private-dev deb libdevel optional arch=any
Checksums-Sha1:
 ae782fa0c05351f705c54815ed215a783d0e2655 569152 qtwayland-opensource-src_5.15.13.orig.tar.xz
 10374a92d6eb2bda3c1d8d2ced04e8511c8b3b79 80944 qtwayland-opensource-src_5.15.13-1.debian.tar.xz
Checksums-Sha256:
 b6d1a10b65c0679899bb5f71e1046ec7d865f3085299a3a2960ddc8419f0ef6c 569152 qtwayland-opensource-src_5.15.13.orig.tar.xz
 809d198093c8022c4f5c55a5e5410e5b503be76a926a1ff5586dea789bac3ce2 80944 qtwayland-opensource-src_5.15.13-1.debian.tar.xz
Files:
 307aa7b48e2d5378167873cedb486298 569152 qtwayland-opensource-src_5.15.13.orig.tar.xz
 42dc372603f570ecad8f1c4c2161ee2b 80944 qtwayland-opensource-src_5.15.13-1.debian.tar.xz

-----BEGIN PGP SIGNATURE-----

iQJHBAEBCgAxFiEEq2sdvrA0LydXHe1qsmYUtFL0RrYFAmXx4EcTHG1pdHlhNTdA
ZGViaWFuLm9yZwAKCRCyZhS0UvRGtgArD/9LFhnnCuvxwfoSbacwKpoECQB1FLL/
up/UoeWFAMHwV70CTRhvnO91jYEU9ycJfJdysRp33R8WQ3N6OzZbPSOW1/Z2CRtI
6rmDOyQLAPmDIwq5vorDtFk9cyQ1nxl/9QiFaiES4JjKsF5T1DoyLQ7bj31MY7y6
ONSvbJMNgwBWc6pk0QlRwB75lxumoS0Tc9ITiQaqebYgbCPKvrsaMjIQGLubPm09
9uBmDIsuCdIoY0jn75PqLkV7zz9D/VwCwilPr+RkiO2tcMbxh3e31L8Oim6eNyDI
uUGf9DLUVffUTFjtpnPGs9r4HLxRAF8qYAge+E9dldWJN6gGrjK3Blyk0SbogbfF
MIJl3FbaYNd1VIdeiN8UZeiDUza9lZhFZez+922kUdIMnqBQ7ms2aU6zdl/Zeo17
YuwpDt+i8iR5kb7RqkRkU0ODjNjoFyfZGWNwo8XG2jrHFHkgrxVgR7KjJ3J8bwev
vijAOBKXlhitCWCHlslAzcxmtZwIXuim0qn+8eRdJMK+kLGVgMq6bcnMNDiOOduI
zPsKC8Y2uKdpLzBH5VKdBG8CCrPI72J8BgN6bovoSIayET0oAZYIgdreFg3dK3y3
4seTb4xOxXViMSdP0pQ2dY3ag0zUQdDvK+BMM6+nkj3BnM/oRk8MoAyzyT8UqNpM
8KPn+p5eFXrlyw==
=e7Zf
-----END PGP SIGNATURE-----
