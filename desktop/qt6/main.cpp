#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickWindow>
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonArray>
#include <QQuickStyle>
#include <QStandardPaths>
#include <QElapsedTimer>
#include <QDebug>

#ifdef MELLIPI_LAYER_SHELL
#include <LayerShellQt/Shell>
#include <LayerShellQt/Window>
#include <QLocalSocket>
#include <QProcess>
#include <QFileInfo>
#include <sys/stat.h>
#include <unistd.h>

class Shell : public QObject {
    Q_OBJECT
    Q_PROPERTY(QStringList apps READ apps CONSTANT)
    Q_PROPERTY(int workspace READ workspace NOTIFY workspaceChanged)
public:
    QQuickWindow *launcher = nullptr;
    QLocalSocket events;
    QByteArray input;
    QString endpoint;
    int current = 1;
    bool locked = true;
    bool login = false;
    const QMap<QString, QString> programs{
        {"Files", "/usr/bin/mellipi-files"}, {"Terminal", "/usr/bin/mellipi-terminal"},
        {"Photos", "/usr/bin/mellipi-photos"}, {"Software", "/usr/bin/mellipi-software"}
    };
    QStringList apps() const { return programs.keys(); }
    int workspace() const { return current; }
    void connectEvents() {
        connect(&events, &QLocalSocket::connected, this, [this] {
            events.write("{\"command\":\"subscribe\"}\n");
        });
        connect(&events,&QLocalSocket::disconnected,this,[] { qApp->exit(2); });
        connect(&events, &QLocalSocket::readyRead, this, [this] {
            input += events.readAll();
            if (input.size() > 1048576) { events.abort(); qApp->exit(2); return; }
            while (const auto length = input.indexOf('\n') + 1) {
                const auto packet = QJsonDocument::fromJson(input.left(length)).object();
                input.remove(0, length);
                const auto snapshot = packet.value("snapshot").toObject();
                if (!snapshot.isEmpty()) {
                    locked = snapshot.value("locked").toBool(true);
                    if (locked && launcher) launcher->hide();
                    const auto desks = snapshot.value("desktops").toArray();
                    for (const auto &value : desks) {
                        auto desk = value.toObject();
                        if (desk.value("active").toBool()) {
                            int next = desk.value("id").toInt() + 1;
                            if (next != current) { current = next; emit workspaceChanged(); }
                        }
                    }
                }
                if (packet.value("event") == "action" && packet.value("action") == "launcher")
                    toggleLauncher();
            }
        });
        events.setReadBufferSize(1048576);
        connect(&events, &QLocalSocket::errorOccurred, this, [](auto) { qApp->exit(2); });
        events.connectToServer(endpoint);
    }
    Q_INVOKABLE void toggleLauncher() {
        if (launcher && !locked) launcher->setVisible(!launcher->isVisible());
    }
    Q_INVOKABLE void openApp(const QString &name) {
        if (locked || !programs.contains(name)) return;
        QProcess process;
        process.setProgram(programs.value(name));
        auto env = QProcessEnvironment::systemEnvironment();
        for (const auto &key : {"LD_LIBRARY_PATH", "QT_PLUGIN_PATH", "QT_WAYLAND_SHELL_INTEGRATION"})
            env.remove(key);
        process.setProcessEnvironment(env);
        if (process.startDetached()) launcher->hide();
    }
    Q_INVOKABLE void lockSession() {
        if (!login || locked) return;
        auto env = QProcessEnvironment::systemEnvironment();
        env.remove("LD_LIBRARY_PATH");
        env.remove("QT_PLUGIN_PATH");
        env.remove("QT_WAYLAND_SHELL_INTEGRATION");
        auto *locker = new QProcess(this);
        locker->setProcessEnvironment(env);
        connect(locker, &QProcess::finished, locker, &QObject::deleteLater);
        connect(locker, &QProcess::errorOccurred, locker, &QObject::deleteLater);
        locker->start("/usr/bin/python3", {"/usr/lib/abstract/screen_lock.py"});
    }
    Q_INVOKABLE void logOut() {
        if (login && !locked) QCoreApplication::quit();
    }
    Q_INVOKABLE void selectWorkspace(int index) {
        if (locked || index < 1 || index > 4) return;
        auto *socket = new QLocalSocket(this);
        connect(socket,&QLocalSocket::connected,socket,[socket,index] {
            socket->write(QJsonDocument(QJsonObject{{"command","workspace"},{"workspace",index}})
                .toJson(QJsonDocument::Compact) + '\n');
            socket->disconnectFromServer();
        });
        connect(socket,&QLocalSocket::disconnected,socket,&QObject::deleteLater);
        connect(socket,&QLocalSocket::errorOccurred,socket,&QObject::deleteLater);
        socket->connectToServer(endpoint);
    }
signals:
    void workspaceChanged();
};
#endif

int main(int argc, char **argv)
{
    QElapsedTimer startup;
    startup.start();
    const bool loginMode = argc == 2 && QByteArray(argv[1]) == "--login-shell";
    const bool panelMode = loginMode || (argc == 2 && QByteArray(argv[1]) == "--nested-shell");
#ifdef MELLIPI_LAYER_SHELL
    if (panelMode) {
        if (loginMode ? (qgetenv("MELLIPI_QT6_LOGIN") != "1" || qgetenv("ORBIT_INSTALLED_SESSION") != "1"
                         || qEnvironmentVariableIsSet("ORBIT_NESTED")) : qgetenv("ORBIT_NESTED") != "1")
            return 2;
        LayerShellQt::Shell::useLayerShell();
    }
#else
    if (panelMode) return 2;
#endif
    QGuiApplication app(argc, argv);
    QQuickStyle::setStyle("Basic");
    const auto settingsPath = qEnvironmentVariable("ORBIT_SETTINGS_FILE",
        QStandardPaths::writableLocation(QStandardPaths::ConfigLocation) + "/abstract/settings.json");
    QFile file(settingsPath);
    QJsonObject settings;
    if (file.open(QIODevice::ReadOnly) && file.size() <= 131072)
        settings = QJsonDocument::fromJson(file.readAll()).object();
    QQmlApplicationEngine engine;
    engine.rootContext()->setContextProperty("mellipiLight", settings.value("mode").toString() == "light");
    engine.rootContext()->setContextProperty("mellipiReducedMotion", settings.value("reducedMotion").toBool());
#ifdef MELLIPI_LAYER_SHELL
    Shell shell;
    if (panelMode) {
        shell.login = loginMode;
        engine.rootContext()->setContextProperty("mellipiLogin", loginMode);
        shell.endpoint = qEnvironmentVariable("ORBIT_NATIVE_CONTROL");
        struct stat info {};
        if (!QFileInfo(shell.endpoint).isAbsolute() ||
            lstat(QFile::encodeName(shell.endpoint).constData(), &info) != 0 ||
            !S_ISSOCK(info.st_mode) || info.st_uid != getuid() || (info.st_mode & 077))
            return 2;
        engine.rootContext()->setContextProperty("shell", &shell);
        engine.load(QUrl("qrc:/Mellipi/ui/Panel.qml"));
        engine.load(QUrl("qrc:/Mellipi/ui/Launcher.qml"));
        if (engine.rootObjects().size() != 2) return 2;
        auto *panel = qobject_cast<QQuickWindow *>(engine.rootObjects().first());
        shell.launcher = qobject_cast<QQuickWindow *>(engine.rootObjects().last());
        if (!panel || !shell.launcher) return 2;
        using L = LayerShellQt::Window;
        auto *bar = L::get(panel);
        bar->setAnchors(L::Anchors(L::AnchorBottom) | L::AnchorLeft | L::AnchorRight);
        bar->setLayer(L::LayerTop);
        bar->setExclusiveZone(48);
        auto *overlay = L::get(shell.launcher);
        overlay->setAnchors({});
        overlay->setLayer(L::LayerOverlay);
        overlay->setExclusiveZone(-1);
        overlay->setKeyboardInteractivity(L::KeyboardInteractivityExclusive);
        app.setQuitOnLastWindowClosed(false);
        shell.connectEvents();
        panel->show();
        return app.exec();
    }
#endif
    engine.load(QUrl("qrc:/Mellipi/ui/Main.qml"));
    if (engine.rootObjects().isEmpty())
        return 1;
    auto *window = qobject_cast<QQuickWindow *>(engine.rootObjects().first());
    if (!window)
        return 1;
    QObject::connect(window, &QQuickWindow::frameSwapped, &app, [&]() {
        qInfo() << "Mellipi Qt 6 first frame:" << startup.elapsed() << "ms";
        if (app.arguments().contains("--smoke"))
            QMetaObject::invokeMethod(&app, &QGuiApplication::quit, Qt::QueuedConnection);
    }, Qt::SingleShotConnection);
    window->show();
    return app.exec();
}

#ifdef MELLIPI_LAYER_SHELL
#include "main.moc"
#endif
