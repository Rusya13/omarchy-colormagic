import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// ColorMagic bar widget: generate images, upscale files/screenshots and
// edit pictures through the ColorMagic cloud API. Long jobs run in the
// background via small Python helpers (backend/*.py, stdlib only); the
// panel submits, polls cm_status.py on a timer, and sends a desktop
// notification when a job finishes.
Panel {
  id: root
  moduleName: "rus.colormagic"
  ipcTarget: "rus.colormagic"
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  // --- Auth / catalog state ---
  property bool signedIn: false
  property string userEmail: ""
  property var models: []
  property string modelsError: ""
  property bool modelsLoading: false

  // --- Generate tab state ---
  property string genPrompt: ""
  property string genModel: setting("defaultModel", "colormagic-image-klein")
  property string genSize: setting("defaultSize", "1024x1024")
  property string genEditImage: ""
  property real genStrength: 0.6
  property string activeTab: "generate"

  // --- Upscale tab state ---
  property string upImage: ""
  property string upModel: setting("upscaleModel", "real-esrgan")
  property int upFactor: setting("upscaleFactor", 2)

  // --- Job state ---
  property var activeJob: null       // {kind, id, label, startedAt}
  property string jobStatus: ""
  property string jobError: ""
  property var lastFiles: []
  property string submitError: ""
  property bool submitting: false
  property bool shotForEdit: false   // screenshot target flag

  readonly property color foreground: Color.popups.text
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property color accent: Color.accent
  readonly property color surface: Color.popups.background
  readonly property color dim: Util.alpha(root.foreground, 0.62)
  readonly property color subtle: Util.alpha(root.foreground, 0.42)
  readonly property color cardSurface: Style.normalFillFor(
    root.foreground, root.accent, root.urgent)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  function backendPath(name) {
    return decodeURIComponent(
      String(Qt.resolvedUrl("backend/" + name)).replace(/^file:\/\//, ""))
  }

  function outDir() {
    return String(setting("outputDir", "~/Pictures/ColorMagic") || "")
  }

  // ----- models -----
  function refreshModels() {
    if (modelsProcess.running) return
    root.modelsLoading = true
    root.modelsError = ""
    modelsRaw = ""
    modelsProcess.command = ["/usr/bin/python3", backendPath("cm_models.py")]
    modelsProcess.running = true
  }

  // ----- submit -----
  function submitGenerate() {
    if (submitProcess.running || root.activeJob) return
    var prompt = root.genPrompt.trim()
    if (prompt === "") { root.submitError = "Describe the image first."; return }
    var cmd = ["/usr/bin/python3", backendPath("cm_generate.py"),
               "--prompt", prompt, "--model", root.genModel,
               "--size", root.genSize]
    if (root.genEditImage.trim() !== "") {
      cmd.push("--input-image"); cmd.push(root.genEditImage.trim())
      cmd.push("--strength"); cmd.push(String(root.genStrength))
    }
    root.submitError = ""
    root.jobError = ""
    root.submitting = true
    submitRaw = ""
    submitProcess.command = cmd
    submitProcess.jobKind = "generation"
    submitProcess.jobLabel = root.genEditImage.trim() !== "" ? "Editing image" : "Generating image"
    submitProcess.running = true
  }

  function submitUpscale() {
    if (submitProcess.running || root.activeJob) return
    var img = root.upImage.trim()
    if (img === "") { root.submitError = "Pick an image, a screenshot, or Latest first."; return }
    var cmd = ["/usr/bin/python3", backendPath("cm_upscale.py"),
               "--image", img, "--model", root.upModel,
               "--factor", String(root.upFactor)]
    root.submitError = ""
    root.jobError = ""
    root.submitting = true
    submitRaw = ""
    submitProcess.command = cmd
    submitProcess.jobKind = "upscale"
    submitProcess.jobLabel = "Upscaling image"
    submitProcess.running = true
  }

  // ----- polling -----
  function pollIntervalMs() {
    return Math.max(2, setting("pollIntervalSec", 3)) * 1000
  }

  function pollOnce() {
    if (!root.activeJob || statusProcess.running) return
    var elapsed = (Date.now() - root.activeJob.startedAt) / 1000
    if (elapsed > Math.max(60, setting("jobTimeoutSec", 300))) {
      root.jobError = "Timed out waiting for the job. It may still finish — check the desktop app gallery."
      root.activeJob = null
      return
    }
    root.jobStatus = `${root.activeJob.label}… ${Math.floor(elapsed)}s`
    statusRaw = ""
    statusProcess.command = ["/usr/bin/python3", backendPath("cm_status.py"),
      "--kind", root.activeJob.kind, "--id", root.activeJob.id,
      "--download", root.outDir()]
    statusProcess.running = true
  }

  function cancelActive() {
    if (!root.activeJob || cancelProcess.running) return
    cancelProcess.command = ["/usr/bin/python3", backendPath("cm_status.py"),
      "--kind", root.activeJob.kind, "--id", root.activeJob.id, "--cancel"]
    cancelProcess.running = true
  }

  function finishJob(data) {
    var job = root.activeJob
    root.activeJob = null
    root.jobStatus = ""
    if (!job) return
    var st = String(data.status || "")
    if (st === "succeeded") {
      root.lastFiles = data.files || []
      root.jobError = ""
      if (setting("notifyOnComplete", true)) {
        var first = root.lastFiles.length > 0 ? String(root.lastFiles[0]) : ""
        var title = job.kind === "upscale" ? "Upscale finished" : "Image ready"
        var body = first !== "" ? first : `${job.label} completed.`
        var args = ["omarchy", "notification", "send",
          "--app-name", "ColorMagic", "-u", "normal", title, body]
        if (first !== "") args.push("--exec", "xdg-open", first)
        Quickshell.execDetached(args)
      }
    } else if (st === "cancelled") {
      root.jobError = "Job cancelled."
    } else {
      var msg = String(data.error || "Job failed.")
      root.jobError = msg
      if (setting("notifyOnFailure", true)) {
        Quickshell.execDetached(["omarchy", "notification", "send",
          "--app-name", "ColorMagic", "-u", "critical",
          "ColorMagic job failed", msg])
      }
    }
  }

  // ----- helpers: latest output / screenshot / open -----
  function fetchLatest(forEdit) {
    if (latestProcess.running) return
    root.shotForEdit = forEdit
    latestRaw = ""
    latestProcess.command = ["/usr/bin/python3", backendPath("cm_status.py"),
      "--latest", "--dir", root.outDir()]
    latestProcess.running = true
  }

  function takeScreenshot(forEdit) {
    if (shotProcess.running) return
    root.shotForEdit = forEdit
    shotRaw = ""
    // Prints the saved file path (no editor).
    shotProcess.command = ["omarchy", "capture", "screenshot", "region", "save"]
    shotProcess.running = true
  }

  function applyImagePath(path) {
    var p = String(path || "").trim()
    if (p === "") return
    if (root.shotForEdit) root.genEditImage = p
    else root.upImage = p
  }

  function openPath(path) {
    var p = String(path || "")
    if (p === "") return
    if (!Qt.openUrlExternally("file://" + p)) {
      openProcess.command = ["xdg-open", p]
      openProcess.running = true
    }
  }

  function openOutDir() {
    openProcess.command = ["xdg-open", root.outDir()]
    openProcess.running = true
  }

  // ----- backend processes -----
  property string modelsRaw: ""
  Process {
    id: modelsProcess
    stdout: StdioCollector { waitForEnd: true; onStreamFinished: root.modelsRaw = String(text || "") }
    stderr: StdioCollector { waitForEnd: true; onStreamFinished: { var e = String(text || "").trim(); if (e !== "") root.modelsError = e } }
    onExited: function(code) {
      root.modelsLoading = false
      if (code !== 0 && root.modelsError === "") { root.modelsError = "models fetch exited " + code; return }
      try {
        var data = JSON.parse(root.modelsRaw)
        if (data.error) {
          root.signedIn = false
          root.userEmail = ""
          root.modelsError = data.error === "not_signed_in" || data.error === "session_expired"
            ? String(data.message || "Not signed in.") : String(data.message || data.error)
        } else {
          root.signedIn = true
          root.models = data.models || []
          var u = data.user || {}
          root.userEmail = String(u.email || "")
          root.modelsError = ""
        }
      } catch (e) { root.modelsError = "Parse error: " + e }
    }
  }

  property string submitRaw: ""
  Process {
    id: submitProcess
    property string jobKind: "generation"
    property string jobLabel: ""
    stdout: StdioCollector { waitForEnd: true; onStreamFinished: root.submitRaw = String(text || "") }
    stderr: StdioCollector { waitForEnd: true; onStreamFinished: { var e = String(text || "").trim(); if (e !== "") root.submitError = e } }
    onExited: function(code) {
      root.submitting = false
      if (code !== 0 && root.submitError === "") { root.submitError = "Submit exited " + code; return }
      try {
        var data = JSON.parse(root.submitRaw)
        if (data.error) {
          if (data.error === "not_signed_in" || data.error === "session_expired") {
            root.signedIn = false
            root.userEmail = ""
          }
          root.submitError = String(data.message || data.error)
          if (data.hint) root.submitError += "\n" + String(data.hint)
        } else {
          root.submitError = ""
          root.lastFiles = []
          root.activeJob = { kind: submitProcess.jobKind, id: String(data.id || ""),
                             label: submitProcess.jobLabel, startedAt: Date.now() }
          root.pollOnce()
        }
      } catch (e) { root.submitError = "Parse error: " + e }
    }
  }

  property string statusRaw: ""
  Process {
    id: statusProcess
    stdout: StdioCollector { waitForEnd: true; onStreamFinished: root.statusRaw = String(text || "") }
    stderr: StdioCollector { waitForEnd: true; onStreamFinished: { var e = String(text || "").trim(); if (e !== "") root.jobError = e } }
    onExited: function(code) {
      if (code !== 0) { if (root.jobError === "") root.jobError = "Poll exited " + code; return }
      try {
        var data = JSON.parse(root.statusRaw)
        if (data.error) { root.jobError = String(data.message || data.error); return }
        root.jobError = ""
        if (data.done) root.finishJob(data)
        else if (root.activeJob) root.jobStatus = `${root.activeJob.label}… ${String(data.status || "working")}`
      } catch (e) { root.jobError = "Poll parse error: " + e }
    }
  }

  Process {
    id: cancelProcess
    stdout: StdioCollector { waitForEnd: true }
    stderr: StdioCollector { waitForEnd: true }
    onExited: {
      // Confirm the cancelled state on the next poll tick.
      root.jobStatus = "Cancelling…"
      root.pollOnce()
    }
  }

  property string latestRaw: ""
  Process {
    id: latestProcess
    stdout: StdioCollector { waitForEnd: true; onStreamFinished: root.latestRaw = String(text || "") }
    stderr: StdioCollector { waitForEnd: true }
    onExited: function(code) {
      if (code !== 0) return
      try {
        var data = JSON.parse(root.latestRaw)
        if (!data.error && data.path) root.applyImagePath(data.path)
        else if (data.error) root.submitError = String(data.message || data.error)
      } catch (e) { /* ignore */ }
    }
  }

  property string shotRaw: ""
  Process {
    id: shotProcess
    stdout: StdioCollector { waitForEnd: true; onStreamFinished: root.shotRaw = String(text || "") }
    stderr: StdioCollector { waitForEnd: true }
    onExited: function(code) {
      if (code !== 0) { root.submitError = "Screenshot cancelled or failed."; return }
      // `save` prints the file path on stdout.
      var lines = root.shotRaw.split("\n").map(function(s) { return s.trim() }).filter(function(s) { return s !== "" })
      if (lines.length > 0) { root.applyImagePath(lines[lines.length - 1]); root.submitError = "" }
    }
  }

  property string loginRaw: ""
  property bool loginRunning: false
  Process {
    id: loginProcess
    stdout: StdioCollector { waitForEnd: true; onStreamFinished: root.loginRaw = String(text || "") }
    stderr: StdioCollector { waitForEnd: true; onStreamFinished: { var e = String(text || "").trim(); if (e !== "") root.modelsError = e } }
    onExited: function(code) {
      root.loginRunning = false
      // Backend prints exactly one JSON doc on stdout; be lenient and
      // parse the last JSON-looking line so wrapper noise never hides
      // the real result. Anything unparseable is shown raw (truncated).
      function parseLogin(raw) {
        var lines = String(raw || "").split("\n")
        for (var i = lines.length - 1; i >= 0; i--) {
          var line = lines[i].trim()
          if (line === "" || line[0] !== "{") continue
          try { return { data: JSON.parse(line) } } catch (e) { /* try earlier */ }
        }
        try { return { data: JSON.parse(String(raw || "")) } } catch (e) { return { parseError: String(e) } }
      }
      if (code !== 0 && root.loginRaw.trim() === "" && root.modelsError === "") { root.modelsError = "Sign-in exited " + code; return }
      var parsed = parseLogin(root.loginRaw)
      if (parsed.parseError) {
        var raw = root.loginRaw.trim() || root.modelsError
        root.modelsError = "Sign-in gave an unreadable answer" + (code !== 0 ? " (exit " + code + ")" : "") + (raw !== "" ? ": " + raw.slice(-300) : ".")
        return
      }
      try {
        var data = parsed.data
        if (data.error) root.modelsError = String(data.message || data.error)
        else root.refreshModels()
      } catch (e) { root.modelsError = "Sign-in parse error: " + e }
    }
  }

  function signIn() {
    if (loginProcess.running) return
    root.loginRunning = true
    root.modelsError = ""
    root.loginRaw = ""
    loginProcess.command = ["/usr/bin/python3", backendPath("cm_login.py"), "--timeout", "300"]
    loginProcess.running = true
  }

  Process { id: openProcess }

  Timer {
    interval: root.pollIntervalMs()
    running: root.activeJob !== null
    repeat: true
    onTriggered: root.pollOnce()
  }

  onOpenedChanged: {
    if (!opened) return
    if (!root.signedIn) root.refreshModels()
    else if (root.models.length === 0) root.refreshModels()
  }

  // ----- derived UI data -----
  function modelOptions() {
    var opts = []
    for (var i = 0; i < root.models.length; i++) {
      var m = root.models[i]
      opts.push({ value: String(m.id), label: String(m.id).replace("colormagic-", "") })
    }
    if (opts.length === 0) opts.push({ value: root.genModel, label: root.genModel })
    return opts
  }

  function sizeOptions() {
    for (var i = 0; i < root.models.length; i++) {
      if (String(root.models[i].id) === root.genModel) return root.models[i].sizes || [root.genSize]
    }
    return [root.genSize]
  }

  function upscaleOptions() {
    return [
      { value: "real-esrgan", label: "Fast (real-esrgan)" },
      { value: "swinir", label: "Sharp (swinir)" },
      { value: "clarity", label: "Creative (clarity, 2x)" },
      { value: "ccsr", label: "Restore (ccsr, 2x)" }
    ]
  }

  function factorOptions() {
    if (root.upModel === "clarity" || root.upModel === "ccsr") return ["2"]
    return ["2", "4"]
  }

  // --- Status bar button ---
  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: ""
    fontFamily: root.fontFamily
    active: root.opened
    tooltipText: root.activeJob ? `${root.activeJob.label}… • Click for status`
      : (root.signedIn ? "ColorMagic • generate, upscale, edit" : "ColorMagic • sign in to start")
    onPressed: function(b) { root.toggle() }
  }

  Rectangle {
    visible: root.activeJob !== null
    width: Style.space(8)
    height: Style.space(8)
    radius: Style.space(4)
    color: root.accent
    anchors.right: button.right
    anchors.top: button.top
    anchors.rightMargin: Style.space(2)
    anchors.topMargin: Style.space(4)
    border.width: 1
    border.color: root.surface
    z: 10
  }

  // --- Popup panel ---
  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    contentWidth: panel.fittedContentWidth(Style.space(440))
    contentHeight: panel.fittedContentHeight(mainColumn.implicitHeight, Style.space(680))

    ScrollView {
      anchors.fill: parent
      contentWidth: width
      clip: true
      ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
      ScrollBar.vertical.policy: ScrollBar.AsNeeded

      Column {
        id: mainColumn
        width: parent.width
        spacing: Style.space(10)
        bottomPadding: Style.space(12)

        RowLayout {
          width: parent.width
          spacing: Style.space(8)
          Text {
            text: "ColorMagic"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.title
            font.bold: true
          }
          Item { Layout.fillWidth: true }
          PanelActionButton {
            iconText: root.modelsLoading ? "󱥸" : "󰑐"
            tooltipText: "Refresh models"
            foreground: root.foreground
            fontFamily: root.fontFamily
            enabled: !root.modelsLoading
            onClicked: root.refreshModels()
          }
        }

        // Auth row
        RowLayout {
          width: parent.width
          spacing: Style.space(8)
          Rectangle {
            width: Style.space(8); height: Style.space(8); radius: Style.space(4)
            color: root.signedIn ? root.accent : root.subtle
            Layout.alignment: Qt.AlignVCenter
          }
          Text {
            text: root.signedIn ? (root.userEmail !== "" ? `Signed in · ${root.userEmail}` : "Signed in")
              : (root.loginRunning ? "Waiting for Google sign-in in your browser…" : "Not signed in")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            elide: Text.ElideRight
            Layout.fillWidth: true
          }
          Button {
            text: root.loginRunning ? "…" : "Sign in"
            enabled: !root.loginRunning && !root.modelsLoading
            onClicked: root.signIn()
          }
        }

        Text {
          width: parent.width
          visible: root.modelsError !== ""
          text: root.modelsError
          color: root.urgent
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.Wrap
        }

        // Tabs
        RowLayout {
          width: parent.width
          Item { Layout.fillWidth: true }
          ButtonGroup {
            foreground: root.foreground
            fontFamily: root.fontFamily
            fontSize: Style.font.caption
            focusable: false
            value: root.activeTab
            options: [
              { value: "generate", label: "Generate" },
              { value: "upscale", label: "Upscale" }
            ]
            onChanged: function(v) { root.activeTab = v }
          }
          Item { Layout.fillWidth: true }
        }

        // ===== Generate tab =====
        Column {
          width: parent.width
          spacing: Style.space(8)
          visible: root.activeTab === "generate"

          PanelSectionHeader {
            width: parent.width
            text: "New image"
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          TextField {
            width: parent.width
            placeholderText: "A noir detective office, firelight, smooth…"
            text: root.genPrompt
            onTextChanged: root.genPrompt = text
            onAccepted: root.submitGenerate()
          }

          RowLayout {
            width: parent.width
            spacing: Style.space(8)
            Dropdown {
              Layout.fillWidth: true
              label: "Model"
              value: root.genModel
              options: root.modelOptions()
              onChanged: function(v) {
                root.genModel = v
                var sizes = root.sizeOptions()
                if (sizes.indexOf(root.genSize) < 0) root.genSize = String(sizes[0])
              }
            }
            Dropdown {
              Layout.fillWidth: true
              label: "Size"
              value: root.genSize
              options: root.sizeOptions()
              onChanged: function(v) { root.genSize = v }
            }
          }

          PanelSectionHeader {
            width: parent.width
            text: "Edit a picture (optional)"
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          RowLayout {
            width: parent.width
            spacing: Style.space(8)
            TextField {
              Layout.fillWidth: true
              placeholderText: "/path/to/input.png"
              text: root.genEditImage
              onTextChanged: root.genEditImage = text
            }
            Button { text: "Latest"; onClicked: root.fetchLatest(true) }
            Button { text: "Shot"; tooltipText: "Select a screen region"; onClicked: root.takeScreenshot(true) }
          }

          RowLayout {
            width: parent.width
            spacing: Style.space(8)
            visible: root.genEditImage.trim() !== ""
            Text {
              text: `Change: ${Math.round(root.genStrength * 100)}%`
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
            PanelSlider {
              Layout.fillWidth: true
              bar: root.bar
              minimum: 0.1
              maximum: 1.0
              step: 0.05
              value: root.genStrength
              onMoved: function(v) { root.genStrength = v }
            }
          }

          Button {
            width: parent.width
            text: root.submitting ? "Submitting…" : (root.genEditImage.trim() !== "" ? "Edit picture" : "Generate")
            enabled: !root.submitting && root.activeJob === null && root.signedIn
            onClicked: root.submitGenerate()
          }
        }

        // ===== Upscale tab =====
        Column {
          width: parent.width
          spacing: Style.space(8)
          visible: root.activeTab === "upscale"

          PanelSectionHeader {
            width: parent.width
            text: "Source image"
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          TextField {
            width: parent.width
            placeholderText: "/path/to/photo.png"
            text: root.upImage
            onTextChanged: root.upImage = text
          }

          RowLayout {
            width: parent.width
            spacing: Style.space(8)
            Button { Layout.fillWidth: true; text: "Latest output"; onClicked: root.fetchLatest(false) }
            Button { Layout.fillWidth: true; text: "Region shot"; onClicked: root.takeScreenshot(false) }
          }

          RowLayout {
            width: parent.width
            spacing: Style.space(8)
            Dropdown {
              Layout.fillWidth: true
              label: "Model"
              value: root.upModel
              options: root.upscaleOptions()
              onChanged: function(v) {
                root.upModel = v
                if ((v === "clarity" || v === "ccsr") && root.upFactor === 4) root.upFactor = 2
              }
            }
            Dropdown {
              Layout.fillWidth: true
              label: "Factor"
              value: String(root.upFactor)
              options: root.factorOptions()
              onChanged: function(v) { root.upFactor = parseInt(v, 10) }
            }
          }

          Button {
            width: parent.width
            text: root.submitting ? "Submitting…" : "Upscale"
            enabled: !root.submitting && root.activeJob === null && root.signedIn
            onClicked: root.submitUpscale()
          }
        }

        // ----- submit errors -----
        Text {
          width: parent.width
          visible: root.submitError !== ""
          text: root.submitError
          color: root.urgent
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.Wrap
        }

        // ----- active job card -----
        BorderSurface {
          width: parent.width
          visible: root.activeJob !== null
          color: root.cardSurface
          radius: Style.cornerRadius
          borderSpec: Border.controlSpec("normal", root.foreground, root.accent, root.urgent)
          implicitHeight: jobRow.implicitHeight + Style.space(16)

          RowLayout {
            id: jobRow
            anchors.fill: parent
            anchors.margins: Style.space(8)
            spacing: Style.space(8)
            Text {
              Layout.fillWidth: true
              text: root.jobStatus !== "" ? root.jobStatus : "Working…"
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
              elide: Text.ElideRight
            }
            Button { text: "Cancel"; onClicked: root.cancelActive() }
          }
        }

        Text {
          width: parent.width
          visible: root.jobError !== "" && root.activeJob === null
          text: root.jobError
          color: root.urgent
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.Wrap
        }

        // ----- result card -----
        BorderSurface {
          width: parent.width
          visible: root.lastFiles.length > 0
          color: root.cardSurface
          radius: Style.cornerRadius
          borderSpec: Border.controlSpec("normal", root.foreground, root.accent, root.urgent)
          implicitHeight: resultCol.implicitHeight + Style.space(16)

          Column {
            id: resultCol
            anchors.fill: parent
            anchors.margins: Style.space(8)
            spacing: Style.space(8)

            Image {
              width: parent.width
              height: Math.min(220, implicitHeight > 0 ? implicitHeight * (width / Math.max(1, implicitWidth)) : 220)
              fillMode: Image.PreserveAspectFit
              cache: false
              asynchronous: true
              source: root.lastFiles.length > 0 ? "file://" + String(root.lastFiles[0]) : ""
            }

            Text {
              width: parent.width
              text: root.lastFiles.length > 0 ? String(root.lastFiles[0]) : ""
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideMiddle
            }

            RowLayout {
              width: parent.width
              spacing: Style.space(8)
              Button {
                Layout.fillWidth: true
                text: "Open"
                onClicked: { if (root.lastFiles.length > 0) root.openPath(root.lastFiles[0]) }
              }
              Button {
                Layout.fillWidth: true
                text: "Upscale this"
                onClicked: {
                  if (root.lastFiles.length > 0) {
                    root.upImage = String(root.lastFiles[0])
                    root.activeTab = "upscale"
                  }
                }
              }
              Button { Layout.fillWidth: true; text: "Folder"; onClicked: root.openOutDir() }
            }
          }
        }
      }
    }
  }
}
