// Acuity Manager — robot project integration.
//
// Drops a single self-contained NT4 helper file into a robot project
// the user already has on disk. Three flavors:
//
//   * Java (WPILib)  → src/main/java/frc/robot/acuity/AcuityClient.java
//   * C++  (WPILib)  → src/main/include/acuity/AcuityClient.h
//   * Python (robotpy) → acuity_client.py at project root
//
// Each helper has zero external dependencies — it only uses NT4 APIs
// that ship with WPILib / robotpy. No vendordep, no Maven artifact,
// no PyPI package: nothing the user has to fetch over the internet.
// The previous version of this code wrote an Acuity.json vendordep
// pointing at a `tech.acuity:acuity-vision` artifact that never
// existed; teams hit that and either silently failed or burned half
// an hour trying to figure out why "Manage Vendor Libraries" couldn't
// resolve it. The drop-a-file approach trades polish (no in-IDE
// "Acuity Vision" entry in the vendordep list) for "it actually
// compiles and runs on first try", which is the right trade.
//
// Detection: we sniff the chosen folder for the right marker file
// (build.gradle for Java/C++, pyproject.toml for Python) and let
// the user override if our guess is wrong.

const { app, dialog, ipcMain, shell } = require('electron');
const fs    = require('fs');
const path  = require('path');

// In a packaged build, electron-builder copies the template tree into
// `process.resourcesPath/libraries/templates/` via the `extraResources`
// config in package.json. In dev (`npm run dev`) it lives next to the
// repo at `../../../libraries/templates/`. Try the packaged path
// first, fall back to dev.
function templatesDir() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'libraries', 'templates');
  }
  return path.join(__dirname, '..', '..', '..', 'libraries', 'templates');
}

function detectProjectType(dir) {
  if (!fs.existsSync(dir) || !fs.statSync(dir).isDirectory()) return null;

  const has = (rel) => fs.existsSync(path.join(dir, rel));

  // pyproject.toml + a [tool.robotpy] section → robotpy.
  if (has('pyproject.toml')) {
    const txt = fs.readFileSync(path.join(dir, 'pyproject.toml'), 'utf8');
    if (txt.includes('robotpy')) return 'python';
  }
  // robotpy projects also sometimes use robot.py at the root.
  if (has('robot.py') && has('pyproject.toml')) return 'python';

  // WPILib Java/C++ projects ship build.gradle. Distinguish by which
  // source tree is present.
  if (has('build.gradle')) {
    if (has(path.join('src', 'main', 'cpp')))  return 'cpp';
    if (has(path.join('src', 'main', 'java'))) return 'java';
    return 'java';  // sane default — Java is the more common WPILib path
  }
  return null;
}

// Where each helper file lands inside the user's project. Returned as
// an absolute path. We mkdir -p the parent for them.
function destPathFor(projectDir, lang) {
  switch (lang) {
    case 'java':
      return path.join(projectDir,
        'src', 'main', 'java', 'frc', 'robot', 'acuity', 'AcuityClient.java');
    case 'cpp':
      return path.join(projectDir,
        'src', 'main', 'include', 'acuity', 'AcuityClient.h');
    case 'python':
      return path.join(projectDir, 'acuity_client.py');
    default:
      throw new Error(`unknown language: ${lang}`);
  }
}

function templatePathFor(lang) {
  const root = templatesDir();
  switch (lang) {
    case 'java':   return path.join(root, 'AcuityClient.java');
    case 'cpp':    return path.join(root, 'AcuityClient.h');
    case 'python': return path.join(root, 'acuity_client.py');
    default: throw new Error(`unknown language: ${lang}`);
  }
}

function installHelper(projectDir, lang) {
  const src  = templatePathFor(lang);
  const dest = destPathFor(projectDir, lang);
  if (!fs.existsSync(src)) {
    throw new Error(
      `template missing on disk: ${src}. ` +
      'If this is a packaged Manager build, the libraries/templates/ ' +
      'tree was not bundled — file a bug.'
    );
  }
  // Don't trip people up by silently overwriting a file they hand-edited.
  // If the destination already exists we keep a `.bak` so they can recover.
  let alreadyInstalled = false;
  if (fs.existsSync(dest)) {
    const before = fs.readFileSync(dest);
    const after  = fs.readFileSync(src);
    if (before.equals(after)) {
      alreadyInstalled = true;
    } else {
      fs.copyFileSync(dest, dest + '.bak');
    }
  }
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.copyFileSync(src, dest);
  return { dest, alreadyInstalled };
}

function snippetForLang(lang) {
  if (lang === 'java') {
    return `// In Robot.java
import frc.robot.acuity.AcuityClient;

private final AcuityClient acuity = AcuityClient.getInstance();

@Override
public void teleopPeriodic() {
  acuity.getBestTag().ifPresent(tag -> {
    SmartDashboard.putNumber("acuity/id",         tag.id());
    SmartDashboard.putNumber("acuity/distance_m", tag.distanceMeters());
    SmartDashboard.putNumber("acuity/yaw_deg",    tag.yawDeg());
  });
}`;
  }
  if (lang === 'cpp') {
    return `// In Robot.cpp
#include "acuity/AcuityClient.h"

acuity::AcuityClient acuity{};

void Robot::TeleopPeriodic() {
  if (auto tag = acuity.GetBestTag()) {
    frc::SmartDashboard::PutNumber("acuity/id",         tag->id);
    frc::SmartDashboard::PutNumber("acuity/distance_m", tag->distanceMeters);
    frc::SmartDashboard::PutNumber("acuity/yaw_deg",    tag->yawDeg);
  }
}`;
  }
  return `# In robot.py
from acuity_client import AcuityClient

class MyRobot(wpilib.TimedRobot):
    def robotInit(self):
        self.acuity = AcuityClient()

    def teleopPeriodic(self):
        tag = self.acuity.get_best_tag()
        if tag is not None:
            wpilib.SmartDashboard.putNumber("acuity/id",         tag.id)
            wpilib.SmartDashboard.putNumber("acuity/distance_m", tag.distance_m)
            wpilib.SmartDashboard.putNumber("acuity/yaw_deg",    tag.yaw_deg)`;
}

function register(ipcMain) {
  ipcMain.handle('libraries:pick-and-detect', async () => {
    const result = await dialog.showOpenDialog({
      title: 'Pick your robot project folder',
      properties: ['openDirectory'],
    });
    if (result.canceled || !result.filePaths.length) {
      return { ok: false, reason: 'cancelled' };
    }
    const dir = result.filePaths[0];
    const detected = detectProjectType(dir);
    return { ok: true, dir, detected };
  });

  ipcMain.handle('libraries:install', async (_e, { dir, lang }) => {
    try {
      if (!fs.existsSync(dir)) {
        return { ok: false, error: 'folder no longer exists' };
      }
      if (!['java', 'cpp', 'python'].includes(lang)) {
        return { ok: false, error: `unknown language: ${lang}` };
      }
      const r = installHelper(dir, lang);
      return {
        ok:        true,
        action:    r.alreadyInstalled ? 'already-installed' : 'wrote-helper',
        destPath:  r.dest,
      };
    } catch (e) {
      return { ok: false, error: e.message };
    }
  });

  ipcMain.handle('libraries:snippet', async (_e, { lang }) => {
    return { ok: true, snippet: snippetForLang(lang), lang };
  });

  ipcMain.handle('libraries:reveal', async (_e, p) => {
    if (p && fs.existsSync(p)) shell.showItemInFolder(p);
    return { ok: true };
  });
}

module.exports = { register };
