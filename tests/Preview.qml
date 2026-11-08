import QtQuick
import QtQuick.Window
import Quickshell
import qs.Commons
import qs.Commons as Commons
import "Music"

ShellRoot {
    readonly property string scenario: Quickshell.env("QQ_PREVIEW_SCENARIO") || "playing"
    Window {
        id: window
        width: scenario === "compact" ? 400 : 500
        height: scenario === "compact" ? 600 : 760
        visible: true
        color: "#1a1b26"
        Rectangle {
            id: capture
            color: Commons.Color.background
            anchors.fill: parent
            NativePanel {
                id: panel
                anchors.fill: parent
                anchors.margins: 20
                service: mock
            }
        }
        QtObject {
            id: mock
            property bool ready: true
            property bool busy: false
            property string errorKey: ""
            property string errorStage: ""
            property string qrImage: ""
            property string loginStatus: ""
            property string pageKind: "songs"
            property string resultKind: "search"
            property string query: "夜晚"
            property string playlistTitle: ""
            property int page: 1
            property bool more: true
            property var requests: []
            property var playlists: []
            property var songs: [
                {
                    mid: "1",
                    title: "夜空里的微光",
                    artist: "晚风乐队"
                },
                {
                    mid: "2",
                    title: "沿着海岸线",
                    artist: "林间"
                },
                {
                    mid: "3",
                    title: "写给明天的信",
                    artist: "星期天计划"
                },
                {
                    mid: "4",
                    title: "城市慢慢睡去",
                    artist: "远山"
                },
                {
                    mid: "5",
                    title: "再见，夏天",
                    artist: "晚风乐队"
                },
                {
                    mid: "6",
                    title: "星光漫游",
                    artist: "北岛"
                }
            ]
            property var state: ({
                    account: {
                        loggedIn: true,
                        name: "音乐爱好者"
                    },
                    track: {
                        mid: "1",
                        title: "夜空里的微光",
                        artist: "晚风乐队 · 深夜电台",
                        cover: scenario === "cover" ? Qt.resolvedUrl("cover.svg") : scenario === "cover-error" ? Qt.resolvedUrl("missing-cover.png") : ""
                    },
                    playing: true,
                    playbackMode: scenario === "shuffle" ? "shuffle" : "sequential",
                    paused: false,
                    position: 83,
                    duration: 246,
                    volume: 65,
                    canPrevious: true,
                    canNext: true
                })
            function request(command, args) {
                requests.push({command: command, args: args});
                if (command === "playback_mode") {
                    state = Object.assign({}, state, {playbackMode: args.mode});
                }
                console.log("ACTION", command, JSON.stringify(args));
            }
            function search(text, page) {
                requests.push({command: "search", query: text});
                console.log("SEARCH", text, page);
            }
        }
        Timer {
            interval: 100
            running: true
            onTriggered: {
                I18n.languageFile.path = Qt.resolvedUrl("language");
                Commons.Color.background = scenario === "light" ? "#f5f1e8" : "#171b22";
                Commons.Color.foreground = scenario === "light" ? "#303b35" : "#e2e7ee";
                Commons.Color.accent = scenario === "light" ? "#397958" : "#9bc6ad";
                if (scenario === "empty" || scenario === "login") {
                    mock.state = {
                        account: {
                            loggedIn: false
                        },
                        track: null
                    };
                    mock.songs = [];
                    mock.query = "";
                    mock.resultKind = "";
                }
                if (scenario === "login") {
                    mock.qrImage = Qt.resolvedUrl("qr.svg").toString();
                    mock.loginStatus = "waiting";
                }
                if (scenario === "error")
                    mock.errorKey = "network_error";
                if (scenario === "playlists") {
                    mock.pageKind = "playlists";
                    mock.playlists = [
                        {
                            id: "1",
                            title: "我喜欢的歌曲"
                        },
                        {
                            id: "2",
                            title: "周末的慢时光"
                        },
                        {
                            id: "3",
                            title: "漫长旅途 · 一路向海"
                        }
                    ];
                }
                if (scenario === "playlist-search") {
                    mock.resultKind = "playlist";
                    mock.playlistTitle = "夜晚的歌单";
                    mock.query = "";
                    mock.more = false;
                    mock.songs = [
                        {mid: "1", title: "夜空里的微光", artist: "晚风乐队", album: "Night Sky"},
                        {mid: "2", title: "沿着海岸线", artist: "林间", album: "海岸"},
                        {mid: "3", title: "城市慢慢睡去", artist: "晚风乐队", album: "City Lights"}
                    ];
                    panel.searchPlaylist = true;
                }
            }
        }
        Timer {
            interval: 500
            running: scenario === "playlist-search"
            onTriggered: {
                function check(condition, message) {
                    if (!condition) throw new Error(message);
                }
                try {
                    panel.input.text = "海岸";
                    check(panel.entries.length === 1 && panel.songIndices[0] === 1, "title filtering");
                    panel.playSong(0);
                    check(mock.requests[0].command === "play" && mock.requests[0].args.index === 1, "original playback index");
                    panel.input.text = "  CITY lights  ";
                    check(panel.entries.length === 1 && panel.songIndices[0] === 2, "case-insensitive album filtering");
                    panel.input.text = "晚风";
                    check(panel.entries.length === 2, "artist filtering");
                    panel.search();
                    check(mock.requests.length === 1, "local search must not request network");
                    panel.input.text = "no match";
                    check(panel.entries.length === 0, "empty results");
                    panel.input.text = "";
                    check(panel.entries.length === 3, "clear restores playlist");
                    mock.resultKind = "favorites";
                    panel.input.text = "晚风";
                    check(panel.entries.length === 2, "favorites filtering");
                    panel.searchPlaylist = false;
                    check(panel.entries.length === 3 && panel.input.text === "", "switch to online resets filter");
                    panel.input.text = "online query";
                    panel.search();
                    check(mock.requests[1].command === "search", "online search still works");
                    panel.searchPlaylist = true;
                    panel.input.text = "晚风";
                    mock.resultKind = "search";
                    check(!panel.localSearch && panel.entries.length === 3, "leaving playlist resets scope");
                    mock.resultKind = "playlist";
                    panel.searchPlaylist = true;
                    panel.input.text = "晚风";
                    console.log("PLAYLIST_SEARCH_TESTS_PASSED");
                } catch (error) {
                    console.error(error);
                    Qt.exit(1);
                }
            }
        }
        Timer {
            interval: 1800
            running: true
            onTriggered: capture.grabToImage(function (result) {
                result.saveToFile(Quickshell.env("QQ_PREVIEW_OUTPUT"));
                Qt.quit();
            })
        }
    }
}
