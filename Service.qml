import QtQuick
import Quickshell
import Quickshell.Io

Item {
    id: root
    property var shell: null
    property bool ready: false
    property bool busy: false
    property string errorKey: ""
    property string errorStage: ""
    property var state: ({account: {loggedIn: false}, track: null})
    property var songs: []
    property var playlists: []
    property string pageKind: "songs"
    property string query: ""
    property string resultKind: ""
    property string playlistTitle: ""
    property int page: 1
    property bool more: false
    property string qrImage: ""
    property string loginStatus: ""
    property int serial: 0
    property int pendingId: 0
    property string pendingCommand: ""
    property var pendingArgs: ({})
    readonly property bool polling: loginStatus === "waiting" || loginStatus === "scanned"

    function request(command, args) {
        if (!ready || busy) return;
        errorKey = "";
        errorStage = "";
        busy = true;
        pendingId = ++serial;
        pendingCommand = command;
        pendingArgs = args || {};
        backend.write(JSON.stringify({id: pendingId, command: command, args: pendingArgs}) + "\n");
    }
    function search(text, number) {
        request("search", {query: text, page: number || 1});
    }
    function receive(line) {
        var message;
        try { message = JSON.parse(line); } catch (_) { errorKey = "backend_error"; return; }
        if (message.event === "ready") { ready = true; state = message.data; return; }
        if (message.event === "state") { state = message.data; return; }
        if (message.event === "error") { errorKey = message.error; return; }
        if (message.id !== pendingId) return;
        var command = pendingCommand;
        busy = false;
        pendingCommand = "";
        if (!message.ok) {
            errorKey = message.error || "backend_error";
            errorStage = message.stage || "";
            console.warn("QQ Music request failed:", command, errorKey, errorStage);
            if (command === "login" || command === "login_poll") {
                loginStatus = "failed";
                qrImage = "";
            }
            return;
        }
        var data = message.data || {};
        if (command === "login") { qrImage = data.image; loginStatus = data.status; }
        if (command === "login_poll") {
            loginStatus = data.status;
            if (!polling) qrImage = "";
        }
        if (command === "login_cancel" || command === "logout") { qrImage = ""; loginStatus = ""; }
        if (command === "logout") { songs = []; playlists = []; more = false; resultKind = ""; playlistTitle = ""; }
        if (command === "search" || command === "playlist" || command === "favorites") {
            songs = data.songs || [];
            pageKind = "songs";
            page = data.page || 1;
            more = !!data.more;
            query = command === "search" ? pendingArgs.query : "";
            resultKind = command;
            playlistTitle = "";
            if (command === "playlist") {
                for (var i = 0; i < playlists.length; i++) {
                    if (String(playlists[i].id) === String(pendingArgs.id)) { playlistTitle = playlists[i].title; break; }
                }
            }
        }
        if (command === "playlists") { playlists = data.playlists || []; pageKind = "playlists"; resultKind = ""; }
        if (command === "status") state = data;
    }
    function restart() {
        if (backend.running) return;
        errorKey = "";
        backend.running = true;
    }
    Process {
        id: backend
        command: ["python3", "-B", "-u", decodeURIComponent(String(Qt.resolvedUrl("backend/main.py")).replace(/^file:\/\//, ""))]
        running: true
        stdinEnabled: true
        stdout: SplitParser { onRead: line => root.receive(line) }
        // Python emits only sanitized protocol errors, never credentials.
        onExited: {
            root.ready = false;
            root.busy = false;
            root.qrImage = "";
            root.loginStatus = "";
            if (!root.errorKey) root.errorKey = "backend_stopped";
        }
    }
    Timer {
        interval: 2500
        repeat: true
        running: root.ready && root.polling
        onTriggered: if (!root.busy) root.request("login_poll");
    }
}
