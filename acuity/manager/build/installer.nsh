; Acuity Manager — custom NSIS hooks.
;
; electron-builder's default NSIS template gives you the generic
; "Welcome to the X Setup Wizard" / "Completing the X Setup Wizard"
; copy out of the box. We override those strings here, plus the run-
; after-finish checkbox label, so the installer reads like an Acuity
; product instead of a stock Windows installer.
;
; The MUI_* defines have to land BEFORE !insertmacro MUI_PAGE_*, which
; happens in electron-builder's main installer.nsi *after* it includes
; this file via `nsis.include`. So we drop the defines into the
; `customHeader` hook electron-builder calls right before its page
; macros run.
;
; Image assets (sidebar + header BMP, installer + uninstaller ICO) are
; wired up via `nsis.*` keys in package.json — keep that as the single
; source of truth, not duplicated here.

!macro customHeader
  ; Welcome page.
  !define MUI_WELCOMEPAGE_TITLE "Welcome to Acuity Manager"
  !define MUI_WELCOMEPAGE_TEXT "Acuity Manager is the laptop companion to the Acuity vision coprocessor.$\r$\n$\r$\nIt auto-discovers Acuity devices on your robot's network, drops the AcuityClient helper into your robot project, and updates firmware in one click.$\r$\n$\r$\nClick Next to continue."

  ; Finish page.
  !define MUI_FINISHPAGE_TITLE "Acuity Manager is ready"
  !define MUI_FINISHPAGE_TEXT "Acuity Manager has been installed.$\r$\n$\r$\nPlug an Acuity device into the robot radio's ethernet port (or join its setup WiFi for first-time configuration) and it will show up in the Devices tab automatically."
  !define MUI_FINISHPAGE_RUN_TEXT "Launch Acuity Manager"

  ; Uninstaller pages — symmetrical wording so the uninstall flow
  ; doesn't suddenly turn back into the generic "Setup Wizard".
  !define MUI_UNWELCOMEPAGE_TITLE "Uninstall Acuity Manager"
  !define MUI_UNWELCOMEPAGE_TEXT "This will remove Acuity Manager from your computer.$\r$\n$\r$\nYour SSH credentials and discovered devices live in your Windows user profile and will not be deleted unless you check the option on the next page.$\r$\n$\r$\nClick Next to continue."
  !define MUI_UNFINISHPAGE_TITLE "Acuity Manager removed"
  !define MUI_UNFINISHPAGE_TEXT "Acuity Manager has been removed from your computer.$\r$\n$\r$\nYour Acuity devices are unaffected. Reinstall Manager any time from acuity-releases on GitHub."

  ; (Don't !define MUI_HEADERIMAGE / MUI_HEADERIMAGE_RIGHT here —
  ; electron-builder sets both on the makensis command line when
  ; `nsis.installerHeader` is configured in package.json. Defining
  ; them a second time aborts makensis with
  ;   !define: "MUI_HEADERIMAGE" already defined!
  ; which we hit on the v0.1.14 release build before this change.)
!macroend
