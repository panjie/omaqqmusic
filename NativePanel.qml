import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import qs.Ui
import qs.Commons
import qs.Commons as Commons

Item {
    id: root
    property var service: null
    readonly property var state: service ? service.state : ({
            account: {},
            track: null
        })
    readonly property bool available: !!service && service.ready && !service.busy
    readonly property bool signedIn: !!state.account.loggedIn
    readonly property bool sounding: !!state.playing && !state.paused
    readonly property color dim: Commons.Util.alpha(foreground, 0.60)
    readonly property color accent: Commons.Color.accent
    readonly property bool showingPlaylists: !!service && service.pageKind === "playlists"
    readonly property var entries: !service ? [] : showingPlaylists ? service.playlists : service.songs
    property color foreground: Commons.Color.foreground
    property alias input: searchInput
    function action(command, args) {
        if (service)
            service.request(command, args);
    }
    function revealRow(row) {
        var flick = libraryScroll.contentItem;
        var top = row.y;
        if (top < flick.contentY)
            flick.contentY = top;
        else if (top + row.height > flick.contentY + flick.height)
            flick.contentY = top + row.height - flick.height;
    }
    function timeLabel(seconds) {
        var n = Math.max(0, Math.floor(seconds || 0));
        return Math.floor(n / 60) + ":" + (n % 60 < 10 ? "0" : "") + n % 60;
    }
    Translations {
        id: strings
        directory: Qt.resolvedUrl("i18n")
    }
    clip: true

    ColumnLayout {
        anchors.fill: parent
        spacing: Style.space(14)

        RowLayout {
            Layout.fillWidth: true
            spacing: Style.space(8)
            PlainLabel {
                text: "󰎈"
                color: root.accent
                font.pixelSize: Style.font.title
            }
            PlainLabel {
                text: strings.t("idle")
                font.bold: true
                font.pixelSize: Style.font.subtitle
            }
            Item {
                Layout.fillWidth: true
            }
            PlainLabel {
                Layout.maximumWidth: root.width * 0.30
                text: root.state.account.loggedIn ? (root.state.account.name || root.state.account.uin || "") : strings.t("signed_out")
                color: root.dim
                font.pixelSize: Style.font.caption
            }
            Button {
                focusable: true
                iconText: root.state.account.loggedIn ? "󰍃" : "󰈉"
                tooltipText: strings.t(root.state.account.loggedIn ? "logout" : "login")
                text: root.signedIn ? "" : strings.t("sign_in")
                enabled: root.available
                onClicked: root.action(root.state.account.loggedIn ? "logout" : "login")
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: playerContent.implicitHeight + Style.space(32)
            radius: Style.cornerRadius
            color: Commons.Util.alpha(root.accent, 0.07)
            border.width: 1
            border.color: Commons.Util.alpha(root.accent, 0.16)
            ColumnLayout {
                id: playerContent
                anchors.fill: parent
                anchors.margins: Style.space(16)
                spacing: Style.space(8)
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Style.space(16)
                    Rectangle {
                        Layout.preferredWidth: Style.space(84)
                        Layout.preferredHeight: Style.space(84)
                        radius: width / 2
                        color: Commons.Util.alpha(root.foreground, 0.04)
                        border.width: 1
                        border.color: Commons.Util.alpha(root.foreground, 0.14)
                        Repeater {
                            model: 3
                            Rectangle {
                                required property int index
                                anchors.centerIn: parent
                                width: parent.width - Style.space(14 + index * 12)
                                height: width
                                radius: width / 2
                                color: "transparent"
                                border.width: 1
                                border.color: Commons.Util.alpha(root.foreground, 0.08)
                            }
                        }
                        Rectangle {
                            anchors.centerIn: parent
                            width: Style.space(34)
                            height: width
                            radius: width / 2
                            color: root.accent
                            PlainLabel {
                                anchors.centerIn: parent
                                text: "󰎈"
                                color: Commons.Color.background
                                font.pixelSize: Style.font.icon
                            }
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: Style.space(5)
                        PlainLabel {
                            Layout.fillWidth: true
                            text: strings.t(!root.state.track ? "now_idle" : root.sounding ? "now_playing" : "now_paused")
                            color: root.accent
                            font.pixelSize: Style.font.caption
                            font.bold: true
                        }
                        PlainLabel {
                            Layout.fillWidth: true
                            text: root.state.track ? root.state.track.title : strings.t("pick_music")
                            font.pixelSize: Style.font.title
                            font.bold: true
                            maximumLineCount: 2
                            wrapMode: Text.Wrap
                        }
                        PlainLabel {
                            Layout.fillWidth: true
                            text: root.state.track ? (root.state.track.artist || root.state.track.album || "") : strings.t("idle_hint")
                            color: root.dim
                            font.pixelSize: Style.font.bodySmall
                        }
                    }
                }
                PanelSlider {
                    id: seekSlider
                    Layout.fillWidth: true
                    enabled: root.available && !!root.state.playing
                    opacity: enabled ? 1 : 0.4
                    minimum: 0
                    maximum: Math.max(1, root.state.duration || 0)
                    value: root.state.position || 0
                    step: 1
                    trackHeight: Style.space(3)
                    trackColor: Commons.Util.alpha(root.foreground, 0.12)
                    fillColor: root.accent
                    knobColor: root.accent
                    onReleased: function (value) {
                        if (enabled)
                            root.action("seek", {
                                seconds: value
                            });
                    }
                    Accessible.name: strings.t("seek")
                }
                RowLayout {
                    Layout.fillWidth: true
                    PlainLabel {
                        text: root.timeLabel(seekSlider.dragging ? seekSlider.liveValue : root.state.position)
                        color: root.dim
                        font.pixelSize: Style.font.caption
                    }
                    Item {
                        Layout.fillWidth: true
                    }
                    PlainLabel {
                        text: root.timeLabel(root.state.duration)
                        color: root.dim
                        font.pixelSize: Style.font.caption
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: Style.space(8)
                    Button {
                        focusable: true
                        iconText: "󰒮"
                        tooltipText: strings.t("previous")
                        enabled: root.available && !!root.state.canPrevious
                        opacity: enabled ? 1 : 0.3
                        onClicked: root.action("previous")
                    }
                    Button {
                        focusable: true
                        iconText: root.sounding ? "󰏤" : "󰐊"
                        tooltipText: strings.t("play")
                        background: root.accent
                        foreground: Commons.Color.background
                        iconSize: Style.space(26)
                        horizontalPadding: Style.space(14)
                        enabled: root.available && !!root.state.track
                        opacity: enabled ? 1 : 0.45
                        onClicked: root.action("toggle")
                    }
                    Button {
                        focusable: true
                        iconText: "󰒭"
                        tooltipText: strings.t("next")
                        enabled: root.available && !!root.state.canNext
                        opacity: enabled ? 1 : 0.3
                        onClicked: root.action("next")
                    }
                    Item {
                        Layout.fillWidth: true
                    }
                    PlainLabel {
                        text: (root.state.volume || 0) <= 0 ? "󰝟" : "󰕾"
                        color: root.dim
                    }
                    PanelSlider {
                        Layout.preferredWidth: Style.space(84)
                        enabled: root.available && !!root.state.playing
                        opacity: enabled ? 1 : 0.4
                        minimum: 0
                        maximum: 100
                        integer: true
                        step: 1
                        value: root.state.volume === undefined ? 70 : root.state.volume
                        trackHeight: Style.space(3)
                        trackColor: Commons.Util.alpha(root.foreground, 0.12)
                        fillColor: root.dim
                        knobColor: root.foreground
                        onReleased: function (value) {
                            root.action("volume", {
                                value: Math.round(value)
                            });
                        }
                        Accessible.name: strings.t("volume")
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Style.space(8)
            TextField {
                id: searchInput
                Layout.fillWidth: true
                maximumLength: 100
                placeholderText: strings.t("search_hint")
                foreground: root.foreground
                selectByMouse: true
                onAccepted: if (root.available && text.trim())
                    root.service.search(text.trim(), 1)
                Accessible.name: strings.t("search")
            }
            Button {
                focusable: true
                iconText: "󰍉"
                tooltipText: strings.t("search")
                enabled: root.available && searchInput.text.trim().length > 0
                onClicked: root.service.search(searchInput.text.trim(), 1)
            }
        }
        RowLayout {
            visible: !!root.state.account.loggedIn
            Layout.fillWidth: true
            spacing: Style.space(8)
            Button {
                Layout.fillWidth: true
                focusable: true
                iconText: "󰋑"
                text: strings.t("favorites")
                selected: !!root.service && root.service.resultKind === "favorites"
                bordered: true
                enabled: root.available
                onClicked: root.action("favorites")
            }
            Button {
                Layout.fillWidth: true
                focusable: true
                iconText: "󰋚"
                text: strings.t("playlists")
                selected: root.showingPlaylists || (!!root.service && root.service.resultKind === "playlist")
                bordered: true
                enabled: root.available
                onClicked: root.action("playlists")
            }
        }
        PanelSeparator {
            Layout.fillWidth: true
            foreground: root.foreground
        }
        RowLayout {
            Layout.fillWidth: true
            PlainLabel {
                Layout.fillWidth: true
                font.bold: true
                text: !root.service ? strings.t("discover") : root.showingPlaylists ? strings.t("playlists") : root.service.resultKind === "search" ? strings.t("search_results").arg(root.service.query) : root.service.resultKind === "favorites" ? strings.t("favorites") : root.service.playlistTitle || strings.t("discover")
            }
            PlainLabel {
                color: root.dim
                font.pixelSize: Style.font.caption
                text: root.service && root.service.busy ? strings.t("working") : strings.tn("item_count", root.entries.length).arg(Commons.I18n.formatNumber(root.entries.length))
            }
        }
        Controls.ScrollView {
            id: libraryScroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth
            Controls.ScrollBar.horizontal.policy: Controls.ScrollBar.AlwaysOff
            Column {
                width: libraryScroll.availableWidth
                spacing: Style.space(8)
                PlainLabel {
                    visible: !!root.service && (root.service.loginStatus === "expired" || root.service.loginStatus === "failed")
                    width: parent.width
                    wrapMode: Text.Wrap
                    color: root.dim
                    text: strings.t("login_" + (root.service ? root.service.loginStatus : "expired"))
                }
                // ---- QR sign-in card ----
                BorderSurface {
                    visible: !!root.service && root.service.qrImage !== ""
                    width: parent.width
                    radius: Style.cornerRadius
                    color: Commons.Util.alpha(root.foreground, 0.05)
                    borderSpec: Border.controlSpec("normal", root.foreground, Commons.Color.accent)
                    implicitHeight: qrColumn.implicitHeight + Style.space(24)

                    Column {
                        id: qrColumn
                        width: parent.width
                        y: Style.space(12)
                        spacing: Style.space(10)

                        Image {
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: Style.space(180)
                            height: width
                            source: root.service ? root.service.qrImage : ""
                            visible: source.toString().length > 0
                            sourceSize.width: 256
                            sourceSize.height: 256
                            fillMode: Image.PreserveAspectFit
                            cache: false
                        }
                        PlainLabel {
                            width: parent.width - Style.space(24)
                            anchors.horizontalCenter: parent.horizontalCenter
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.Wrap
                            visible: !!root.service && root.service.loginStatus !== ""
                            color: root.service && root.service.loginStatus === "failed" ? Commons.Color.urgent : root.dim
                            font.pixelSize: Style.font.bodySmall
                            text: strings.t("login_" + (root.service ? root.service.loginStatus : "waiting"))
                        }
                        Button {
                            anchors.horizontalCenter: parent.horizontalCenter
                            focusable: true
                            text: strings.t("cancel")
                            enabled: root.available
                            onClicked: root.action("login_cancel")
                        }
                    }
                }

                // ---- Error banner ----
                BorderSurface {
                    visible: !!root.service && root.service.errorKey !== ""
                    width: parent.width
                    radius: Style.cornerRadius
                    color: Commons.Util.alpha(Commons.Color.urgent, 0.1)
                    borderSpec: Border.controlSpec("normal", Commons.Color.urgent, Commons.Color.urgent)
                    implicitHeight: errorRow.implicitHeight + Style.space(20)

                    Row {
                        id: errorRow
                        width: parent.width - Style.space(20)
                        x: Style.space(10)
                        y: Style.space(10)
                        spacing: Style.space(8)
                        PlainLabel {
                            anchors.verticalCenter: parent.verticalCenter
                            text: "󰀦"
                            color: Commons.Color.urgent
                            font.pixelSize: Style.font.icon
                        }
                        PlainLabel {
                            width: parent.width - Style.space(36)
                            anchors.verticalCenter: parent.verticalCenter
                            wrapMode: Text.Wrap
                            color: Commons.Color.urgent
                            font.pixelSize: Style.font.bodySmall
                            text: root.service && root.service.errorStage ? strings.t("error_details").arg(strings.t("error_" + root.service.errorKey)).arg(strings.t("stage_" + root.service.errorStage)) : strings.t("error_" + (root.service ? root.service.errorKey : "backend_stopped"))
                        }
                    }
                }

                Column {
                    visible: root.entries.length === 0 && !(root.service && (root.service.busy || root.service.qrImage || root.service.errorKey))
                    width: parent.width
                    topPadding: Style.space(22)
                    spacing: Style.space(10)
                    PlainLabel {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "󰎈"
                        color: root.accent
                        font.pixelSize: Style.space(34)
                    }
                    PlainLabel {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        text: strings.t(root.service && (root.service.resultKind || root.showingPlaylists) ? "empty" : "welcome_title")
                        font.bold: true
                    }
                    PlainLabel {
                        width: parent.width - Style.space(40)
                        anchors.horizontalCenter: parent.horizontalCenter
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.Wrap
                        text: strings.t(root.service && (root.service.resultKind || root.showingPlaylists) ? "empty_hint" : "welcome_hint")
                        color: root.dim
                        font.pixelSize: Style.font.bodySmall
                    }
                }
                Repeater {
                    model: root.showingPlaylists ? [] : root.entries
                    SongRow {}
                }
                Repeater {
                    model: root.showingPlaylists ? root.entries : []
                    PlaylistRow {}
                }
                Button {
                    visible: !!root.service && !root.service.ready
                    width: parent.width
                    focusable: true
                    iconText: "󰑢"
                    text: strings.t("retry")
                    onClicked: root.service.restart()
                }
            }
        }
        RowLayout {
            visible: !!root.service && root.service.pageKind === "songs" && root.service.query !== ""
            Layout.fillWidth: true
            Button {
                focusable: true
                iconText: "󰁍"
                tooltipText: strings.t("page_previous")
                enabled: root.available && !!root.service && root.service.page > 1
                onClicked: root.service.search(root.service.query, root.service.page - 1)
            }
            PlainLabel {
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                color: root.dim
                font.pixelSize: Style.font.caption
                text: strings.t("page_label").arg(Commons.I18n.formatNumber(root.service ? root.service.page : 1))
            }
            Button {
                focusable: true
                iconText: "󰁔"
                tooltipText: strings.t("page_next")
                enabled: root.available && !!root.service && root.service.more
                onClicked: root.service.search(root.service.query, root.service.page + 1)
            }
        }
    }
    Connections {
        target: root.service
        function onSongsChanged() {
            libraryScroll.contentItem.contentY = 0;
        }
        function onPlaylistsChanged() {
            libraryScroll.contentItem.contentY = 0;
        }
        function onErrorKeyChanged() {
            if (root.service.errorKey)
                libraryScroll.contentItem.contentY = 0;
        }
        function onQrImageChanged() {
            libraryScroll.contentItem.contentY = 0;
        }
    }
    // Animated equalizer marks for the row that is playing right now.
    component EqBars: Item {
        id: eq
        property bool active: false
        property color barColor: Commons.Color.accent
        width: Style.space(24)
        height: Style.space(14)
        anchors.verticalCenter: parent.verticalCenter
        Row {
            anchors.centerIn: parent
            spacing: Style.space(2)
            Repeater {
                model: 3
                Rectangle {
                    id: bar
                    required property int index
                    width: Style.space(2)
                    radius: width / 2
                    color: eq.barColor
                    opacity: eq.active ? 1 : 0.7
                    height: eq.active ? [6, 12, 8][bar.index] : Style.space(3)
                    SequentialAnimation on height {
                        running: eq.active && !Style.reduceMotion
                        loops: Animation.Infinite
                        NumberAnimation {
                            to: 4 + bar.index * 3
                            duration: Style.duration(260 + bar.index * 90)
                            easing.type: Easing.OutCubic
                        }
                        NumberAnimation {
                            to: 10 + bar.index * 2
                            duration: Style.duration(320 - bar.index * 60)
                            easing.type: Easing.OutCubic
                        }
                    }
                }
            }
        }
    }

    component SongRow: Rectangle {
        id: songRow
        required property var modelData
        required property int index
        function activate() {
            root.action("play", {
                index: songRow.index
            });
        }
        readonly property bool current: !!root.state.track && root.state.track.mid === songRow.modelData.mid
        readonly property bool sounding: songRow.current && root.state.playing && !root.state.paused
        activeFocusOnTab: root.available
        onActiveFocusChanged: if (activeFocus)
            root.revealRow(this)
        Accessible.role: Accessible.Button
        Accessible.name: modelData.title
        Keys.onReturnPressed: if (root.available)
            activate()
        Keys.onSpacePressed: if (root.available)
            activate()
        width: parent.width
        height: Style.space(60)
        radius: Style.cornerRadius
        opacity: root.available ? 1 : 0.6
        color: activeFocus || mouse.containsMouse ? Style.hoverFillFor(root.foreground, Commons.Color.accent) : songRow.current ? Commons.Util.alpha(Commons.Color.accent, 0.16) : "transparent"
        Behavior on color {
            ColorAnimation {
                duration: Style.duration(120)
            }
        }

        Row {
            anchors.fill: parent
            anchors.leftMargin: Style.space(10)
            anchors.rightMargin: Style.space(10)
            spacing: Style.space(10)

            EqBars {
                visible: songRow.current
                active: songRow.sounding
            }
            PlainLabel {
                visible: !songRow.current
                anchors.verticalCenter: parent.verticalCenter
                width: Style.space(24)
                horizontalAlignment: Text.AlignHCenter
                color: root.dim
                font.pixelSize: Style.font.caption
                text: String(songRow.index + 1)
            }
            Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.space(2)
                width: parent.width - Style.space(46)
                PlainLabel {
                    width: parent.width
                    text: songRow.modelData.title
                    color: songRow.current ? Commons.Color.accent : root.foreground
                    font.pixelSize: Style.font.body
                    font.bold: songRow.current
                }
                PlainLabel {
                    width: parent.width
                    visible: text !== ""
                    text: songRow.modelData.artist
                    color: root.dim
                    font.pixelSize: Style.font.caption
                }
            }
        }

        MouseArea {
            id: mouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            enabled: root.available
            onClicked: {
                songRow.forceActiveFocus();
                songRow.activate();
            }
        }
    }

    component PlaylistRow: Rectangle {
        id: playlistRow
        function activate() {
            root.action("playlist", {
                id: playlistRow.modelData.id
            });
        }
        required property var modelData
        activeFocusOnTab: root.available
        onActiveFocusChanged: if (activeFocus)
            root.revealRow(this)
        Accessible.role: Accessible.Button
        Accessible.name: modelData.title
        Keys.onReturnPressed: if (root.available)
            activate()
        Keys.onSpacePressed: if (root.available)
            activate()
        width: parent.width
        height: Style.space(60)
        radius: Style.cornerRadius
        opacity: root.available ? 1 : 0.6
        color: activeFocus || mouse.containsMouse ? Style.hoverFillFor(root.foreground, Commons.Color.accent) : "transparent"
        Behavior on color {
            ColorAnimation {
                duration: Style.duration(120)
            }
        }

        Row {
            anchors.fill: parent
            anchors.leftMargin: Style.space(10)
            anchors.rightMargin: Style.space(10)
            spacing: Style.space(10)

            PlainLabel {
                anchors.verticalCenter: parent.verticalCenter
                text: "󰋚"
                color: Commons.Color.accent
                font.pixelSize: Style.font.icon
            }
            Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.space(2)
                width: parent.width - Style.space(46)
                PlainLabel {
                    width: parent.width
                    text: playlistRow.modelData.title
                    font.pixelSize: Style.font.body
                    font.bold: true
                }
                PlainLabel {
                    width: parent.width
                    text: strings.t("open_playlist")
                    color: root.dim
                    font.pixelSize: Style.font.caption
                }
            }
        }

        MouseArea {
            id: mouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            enabled: root.available
            onClicked: {
                playlistRow.forceActiveFocus();
                playlistRow.activate();
            }
        }
    }
}
