import QtQuick 2.15
import QtQuick.Controls 2.15
import Omarchy.Bar 1.0

BarWidget {
    id: root
    property int bookmarkCount: 0
    property bool hasNewBookmarks: false
    property var lastSeenCount: 0

    // No automatic polling timer. Bookmark count is only refreshed when the
    // user explicitly triggers it: bar startup (once), right-click "Refresh",
    // or after closing Xmark (which may have added/deleted bookmarks).

    Component.onCompleted: {
        updateCount(true)
    }

    function updateCount(clearSeen) {
        var process = Qt.createComponent("Process.qml")
        if (process.status === Component.Ready) {
            var proc = process.createObject(root, {
                "program": "xmark",
                "arguments": ["--count"],
                "onFinished": function(exitCode, output) {
                    var count = parseInt(output.trim())
                    if (!isNaN(count)) {
                        bookmarkCount = count
                        if (clearSeen === true) {
                            lastSeenCount = count
                            hasNewBookmarks = false
                        } else {
                            hasNewBookmarks = count > lastSeenCount
                        }
                    }
                }
            })
        }
    }

    function openXmark() {
        var process = Qt.createComponent("Process.qml")
        if (process.status === Component.Ready) {
            process.createObject(root, {
                "program": "ghostty",
                "arguments": ["-e", "xmark"],
                "onFinished": function() {
                    refresh(true)
                }
            })
        }
    }

    function openXComBookmarks() {
        Qt.openUrlExternally("https://x.com/i/bookmarks")
    }

    function refresh(clearSeen) {
        var process = Qt.createComponent("Process.qml")
        if (process.status === Component.Ready) {
            process.createObject(root, {
                "program": "xmark",
                "arguments": ["--refresh"],
                "onFinished": function() {
                    updateCount(clearSeen === true)
                }
            })
        }
    }

    Row {
        id: widgetRow
        spacing: 4
        height: parent.height

        Rectangle {
            id: badge
            width: 24
            height: 24
            radius: 12
            color: hasNewBookmarks ? "#1DA1F2" : "#666666"
            border.color: hasNewBookmarks ? "#1DA1F2" : "transparent"
            border.width: hasNewBookmarks ? 2 : 0
            visible: bookmarkCount > 0

            Text {
                anchors.centerIn: parent
                text: bookmarkCount > 99 ? "99+" : bookmarkCount
                color: "white"
                font.pixelSize: 12
                font.bold: true
            }
        }

        Label {
            id: iconLabel
            text: "🔖"
            font.pixelSize: 16
            color: hasNewBookmarks ? "#1DA1F2" : theme.textColor
        }
    }

    MouseArea {
        anchors.fill: parent
        onClicked: openXmark()
        onPressed: {
            if (mouse.button === Qt.RightButton) {
                contextMenu.popup()
            }
        }
    }

    Menu {
        id: contextMenu

        MenuItem {
            text: "Open Xmark"
            onTriggered: openXmark()
        }

        MenuItem {
            text: "Refresh"
            onTriggered: refresh()
        }

        MenuSeparator {}

        MenuItem {
            text: "Open X.com/bookmarks"
            onTriggered: openXComBookmarks()
        }
    }
}