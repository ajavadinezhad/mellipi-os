import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import Quickshell

ShellRoot {
    id: root
    property var objects: []
    property var links: []
    property var workspaces: []
    property string workspace: "personal"
    property string message: "Connecting to Abstract core…"
    property bool providerReady: false
    property var attached: []
    property string answer: ""
    property bool busy: false
    property string jobId: ""
    function request(path, data, callback) {
        const xhr = new XMLHttpRequest();
        xhr.open(data === null ? "GET" : "POST", "http://127.0.0.1:4783/api/" + path);
        xhr.setRequestHeader("Content-Type", "application/json");
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE) return;
            try {
                const result = JSON.parse(xhr.responseText);
                if (xhr.status < 200 || xhr.status >= 300) { root.message = result.error || "Request failed"; root.busy = false; return; }
                callback(result);
            } catch(e) { root.message = "Core unavailable. Start python3 core.py"; root.busy = false; }
        };
        xhr.send(data === null ? "" : JSON.stringify(data));
    }
    function refresh() {
        request("state", null, function(s) {
            root.objects = s.objects; root.links = s.links; root.workspaces = s.workspaces;
            root.providerReady = s.ai;
            root.message = s.ai ? "AI ready · only attached context is sent" : "AI disconnected · configure a provider to enable";
        });
    }
    function visibleObjects(query) {
        return objects.filter(function(o) {
            return links.some(function(l) { return l.workspace === root.workspace && l.object === o.id; })
                && (o.title + " " + o.body).toLowerCase().includes(query.toLowerCase());
        });
    }
    Component.onCompleted: refresh()
    Timer {
        interval: 800; running: root.busy && root.jobId !== ""; repeat: true
        onTriggered: root.request("jobs/" + root.jobId, null, function(j) {
            if (j.status === "done") { root.answer = j.result; root.busy = false; root.jobId = ""; }
            if (j.status === "error") { root.answer = j.error; root.busy = false; root.jobId = ""; }
        })
    }
    FloatingWindow {
        id: window
        title: "Abstract · Connected workspace"
        width: 1180; height: 760
        color: "#101815"
        RowLayout {
            anchors.fill: parent; spacing: 0
            Rectangle {
                Layout.preferredWidth: 180; Layout.fillHeight: true; color: "#15201a"
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 20; spacing: 15
                    Label { text: "◉ orbit"; color: "#c5e3cf"; font.pixelSize: 28; font.weight: Font.Medium }
                    Label { text: "WORKSPACES"; color: "#8aa693"; font.pixelSize: 10; Layout.topMargin: 35 }
                    Repeater {
                        model: root.workspaces
                        Button {
                            required property var modelData
                            text: modelData.name; Layout.fillWidth: true; highlighted: root.workspace === modelData.id
                            onClicked: root.workspace = modelData.id
                        }
                    }
                    Item { Layout.fillHeight: true }
                    Label { text: "● LOCAL FIRST"; color: "#9bbb9d"; font.pixelSize: 10 }
                }
            }
            ColumnLayout {
                Layout.fillWidth: true; Layout.fillHeight: true; Layout.margins: 28; spacing: 16
                Label { text: "A LITTLE LESS FRICTION"; font.pixelSize: 10; color: "#a9c4af" }
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: root.workspace.charAt(0).toUpperCase() + root.workspace.slice(1); color: "#e0eee4"; font.pixelSize: 36; Layout.fillWidth: true }
                    Button { text: "+ Capture"; onClicked: capture.open() }
                }
                Label { text: "Bring your context together. Take it anywhere."; color: "#91a699" }
                TextField { id: search; placeholderText: "Find a thought, a link, a piece of your work…"; Layout.fillWidth: true }
                Rectangle {
                    Layout.fillWidth: true; Layout.preferredHeight: 140; radius: Theme.corner(14); color: "#293f30"
                    Column {
                        anchors.fill: parent; anchors.margins: 23; spacing: 12
                        Label { text: "One thought. A thousand possibilities."; color: "#d9e8ce"; font.pixelSize: 23 }
                        Label { text: "Capture once. Connect across workspaces.\nChoose the context your AI can use."; color: "#b0c5b4"; lineHeight: 1.5 }
                    }
                }
                Label { text: "YOUR CONTEXT"; color: "#9bb5a1"; font.pixelSize: 11 }
                ListView {
                    Layout.fillWidth: true; Layout.fillHeight: true; spacing: 12; clip: true
                    model: root.visibleObjects(search.text)
                    delegate: Rectangle {
                        id: card
                        required property var modelData
                        width: ListView.view.width; height: details.implicitHeight + 30; radius: Theme.corner(10); color: "#1d2b22"
                        ColumnLayout {
                            id: details; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 15; spacing: 9
                            Label { text: card.modelData.title; color: "#deeadf"; font.pixelSize: 16; Layout.fillWidth: true; elide: Text.ElideRight }
                            Label { text: card.modelData.body; color: "#a5baaa"; wrapMode: Text.Wrap; maximumLineCount: 3; elide: Text.ElideRight; Layout.fillWidth: true }
                            RowLayout {
                                CheckBox {
                                    text: "Attach to AI"; checked: root.attached.indexOf(card.modelData.id) >= 0
                                    onClicked: {
                                        let ids = root.attached.slice(); let i = ids.indexOf(card.modelData.id);
                                        if (i >= 0) ids.splice(i,1); else ids.push(card.modelData.id);
                                        root.attached = ids;
                                    }
                                }
                                ComboBox { id: destination; model: root.workspaces; textRole: "name"; valueRole: "id"; Layout.preferredWidth: 115 }
                                Button { text: "Share"; onClicked: root.request("share", {object: card.modelData.id, workspace: destination.currentValue}, function() {root.refresh();}) }
                            }
                        }
                    }
                }
            }
            Rectangle {
                Layout.preferredWidth: 300; Layout.fillHeight: true; color: "#18231b"
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 22; spacing: 18
                    Label { text: "✧ Abstract intelligence"; color: "#d2e6d1"; font.pixelSize: 19 }
                    Label { text: "A little context.\nA clearer next step."; color: "#e0ecdd"; font.pixelSize: 26; Layout.topMargin: 24 }
                    Label { text: "Attached items: " + root.attached.length; color: "#a8c0aa" }
                    Label { text: root.message; color: "#9bb79c"; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    ScrollView {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        TextArea { text: root.answer; readOnly: true; wrapMode: TextEdit.Wrap; color: "#d4e4d1" }
                    }
                    TextArea { id: prompt; placeholderText: "What would you like to work on?"; wrapMode: TextEdit.Wrap; Layout.fillWidth: true; Layout.preferredHeight: 100 }
                    Button {
                        text: root.busy ? "Working…" : "Ask Abstract →"; enabled: root.providerReady && !root.busy; Layout.fillWidth: true
                        onClicked: {
                            if (!prompt.text.trim()) return;
                            root.busy = true;
                            root.request("ai", {prompt: prompt.text, objects: root.attached, workspace: root.workspace}, function(j) { root.jobId = j.id; });
                        }
                    }
                    Button {
                        text: "Save answer"; enabled: root.answer !== "" && !root.busy; Layout.fillWidth: true
                        onClicked: root.request("objects", {kind: "result", title: prompt.text.slice(0,100) || "AI answer", body: root.answer, workspace: root.workspace}, function() {root.refresh();})
                    }
                }
            }
        }
        Popup {
            id: capture; anchors.centerIn: parent; width: 450; height: 370; modal: true; focus: true
            ColumnLayout {
                anchors.fill: parent; spacing: 14
                Label { text: "Capture context"; font.pixelSize: 25 }
                TextField { id: objectTitle; placeholderText: "Title"; Layout.fillWidth: true }
                TextArea { id: objectBody; placeholderText: "Paste text, a thought, or a URL…"; wrapMode: TextEdit.Wrap; Layout.fillWidth: true; Layout.fillHeight: true }
                Button { text: "Capture →"; enabled: objectTitle.text.trim() !== "" && objectBody.text.trim() !== ""; onClicked: root.request("objects", {title: objectTitle.text, body: objectBody.text, kind: "note", workspace: root.workspace}, function() {capture.close(); objectTitle.text=""; objectBody.text=""; root.refresh();}) }
            }
        }
    }
}
