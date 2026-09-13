import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Bar slot for Xmark: shows the bookmark count, opens the TUI, refreshes on
// request. No background polling — every check is user-triggered (bar
// startup once, or an explicit click) to keep X API credit usage tied to
// actual use.
//
// Opening Xmark and opening a browser both go through Quickshell.execDetached
// via the omarchy-launch-* helpers, which hand off to uwsm-app/systemd-run and
// return immediately — there is no reliable signal for "the user closed the
// terminal", so this widget does not attempt to auto-refresh after opening.
BarWidget {
  id: root
  moduleName: "dailen.xmark"

  readonly property string xmarkBin: Quickshell.env("HOME") + "/.local/bin/xmark"

  property int bookmarkCount: 0
  property bool hasNewBookmarks: false
  property int lastSeenCount: 0

  function updateCount(clearSeen) {
    if (countProc.running) return
    countProc.clearSeen = clearSeen === true
    countProc.running = true
  }

  function refresh() {
    if (refreshProc.running || countProc.running) return
    refreshProc.running = true
  }

  function openXmark() {
    Quickshell.execDetached(["omarchy-launch-terminal", root.xmarkBin])
  }

  function openXComBookmarks() {
    Quickshell.execDetached(["omarchy-launch-browser", "https://x.com/i/bookmarks"])
  }

  Component.onCompleted: updateCount(true)

  Process {
    id: countProc
    property bool clearSeen: false
    command: [root.xmarkBin, "--count"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var n = parseInt(String(text).trim())
        if (!isNaN(n)) {
          root.bookmarkCount = n
          if (countProc.clearSeen) {
            root.lastSeenCount = n
            root.hasNewBookmarks = false
          } else {
            root.hasNewBookmarks = n > root.lastSeenCount
          }
        }
      }
    }
    stderr: StdioCollector { waitForEnd: true }
  }

  Process {
    id: refreshProc
    command: [root.xmarkBin, "--refresh"]
    onExited: root.updateCount(true)
    stdout: StdioCollector { waitForEnd: true }
    stderr: StdioCollector { waitForEnd: true }
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "\uD83D\uDD16" + (root.bookmarkCount > 0 ? " " + root.bookmarkCount : "")
    active: root.hasNewBookmarks
    tooltipText: "Xmark \u2014 " + root.bookmarkCount + " bookmark" + (root.bookmarkCount === 1 ? "" : "s")
      + (root.hasNewBookmarks ? " (new)" : "")
      + "\nClick: open \u00b7 Right-click: refresh \u00b7 Middle-click: x.com/bookmarks"

    onPressed: function(b) {
      if (b === Qt.RightButton) root.refresh()
      else if (b === Qt.MiddleButton) root.openXComBookmarks()
      else root.openXmark()
    }
  }
}