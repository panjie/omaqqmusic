import QtQuick
import Quickshell
import qs.Ui
import qs.Commons
import qs.Commons as Commons

BarWidget {
    id: root
    moduleName: "panjie.omaqqmusic"
    property bool popupOpen: false
    readonly property var service: bar && bar.shell ? bar.shell.serviceFor(moduleName) : null
    readonly property var state: service ? service.state : ({
            account: {},
            track: null
        })
    readonly property color foreground: bar ? bar.foreground : Commons.Color.foreground
    implicitWidth: vertical ? barSize : Math.min(label.implicitWidth, Style.space(220)) + Style.space(20)
    implicitHeight: barSize
    function close() {
        popupOpen = false;
    }
    function action(command, args) {
        if (service)
            service.request(command, args);
    }
    activeFocusOnTab: true
    Keys.onReturnPressed: popupOpen = !popupOpen
    Keys.onSpacePressed: action("toggle")
    Accessible.role: Accessible.Button
    Accessible.name: "QQ Music"
    Rectangle {
        anchors.fill: parent
        anchors.margins: Style.space(3)
        radius: Style.cornerRadius
        color: Commons.Util.alpha(root.foreground, root.popupOpen || root.activeFocus ? 0.12 : barMouse.containsMouse ? 0.06 : 0)
        Behavior on color {
            ColorAnimation {
                duration: Style.duration(120)
            }
        }
    }
    PlainLabel {
        id: label
        anchors.centerIn: parent
        width: Math.min(implicitWidth, parent.width - Style.space(12))
        text: root.vertical ? "󰎈" : (root.state.playing && !root.state.paused ? "󰐊  " : "󰎈  ") + (root.state.track ? root.state.track.title : "QQ 音乐")
        color: root.bar ? root.bar.barForeground : root.foreground
    }
    MouseArea {
        id: barMouse
        hoverEnabled: true
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        acceptedButtons: Qt.LeftButton | Qt.MiddleButton
        onClicked: mouse => {
            if (mouse.button === Qt.MiddleButton)
                root.action("toggle");
            else
                root.popupOpen = !root.popupOpen;
        }
    }
    KeyboardPanel {
        id: popup
        anchorItem: root
        bar: root.bar
        owner: root
        open: root.popupOpen
        focusTarget: panel.input
        contentWidth: fittedContentWidth(Style.space(460))
        contentHeight: fittedContentHeight(Style.space(720))
        NativePanel {
            id: panel
            anchors.fill: parent
            service: root.service
            foreground: root.foreground
        }
    }
}
