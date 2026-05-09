// Acuity Manager — library installer.
//
// Installs the Acuity client library into a robot project the user
// already has on disk. We support three flavors:
//
//   * Java (WPILib)  → drop Acuity.json into <project>/vendordeps/
//   * C++  (WPILib)  → same JSON, same place (vendordep is shared)
//   * Python (robotpy) → add `acuity-vision>=0.1` to
//                        <project>/pyproject.toml [tool.robotpy].requires
//
// Detection: we sniff the chosen folder for the right marker file
// (build.gradle for Java/C++, pyproject.toml for Python) and let
// the user override if our guess is wrong.

const { app, dialog, ipcMain, shell } = require('electron');
const fs    = require('fs');
const path  = require('path');

// In a packaged build, electron-builder copies the vendordep JSON
// into `process.resourcesPath/libraries/Acuity.json` via the
// `extraResources` config in package.json. In dev (`npm run dev`)
// it lives next to the repo at `../../../libraries/Acuity.json`.
// Try the packaged path first, fall back to dev.
function vendordepPath() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'libraries', 'Acuity.json');
  }
  return path.join(__dirname, '..', '..', '..', 'libraries', 'Acuity.json');
}

function detectProjectType(dir) {
  if (!fs.existsSync(dir) || !fs.statSync(dir).isDirectory()) return null;

  const has = (rel) => fs.existsSync(path.join(dir, rel));

  // pyproject.toml + a [tool.robotpy] section → Python robotpy.
  if (has('pyproject.toml')) {
    const txt = fs.readFileSync(path.join(dir, 'pyproject.toml'), 'utf8');
    if (txt.includes('robotpy')) return 'python';
  }
  // robotpy projects also sometimes use robotpy.toml or robot.py at the root.
  if (has('robot.py') && has('pyproject.toml')) return 'python';

  // WPILib Java/C++ projects ship build.gradle. We distinguish by the
  // presence of a `src/main/cpp/` tree vs `src/main/java/`.
  if (has('build.gradle')) {
    if (has(path.join('src', 'main', 'cpp')))  return 'cpp';
    if (has(path.join('src', 'main', 'java'))) return 'java';
    return 'java';  // fall through — Java is the more common default
  }
  return null;
}

function installVendordep(projectDir) {
  const dest = path.join(projectDir, 'vendordeps', 'Acuity.json');
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.copyFileSync(vendordepPath(), dest);
  return dest;
}

function installPythonDep(projectDir) {
  // Idempotent edit of pyproject.toml's [tool.robotpy] requires list.
  // We don't pull in a TOML parser — the section we touch is a simple
  // line-level array literal in 99% of robotpy projects, and a
  // text-level edit is the smallest change that works.
  const tomlPath = path.join(projectDir, 'pyproject.toml');
  let txt = fs.readFileSync(tomlPath, 'utf8');
  if (txt.includes('"acuity-vision')) {
    return { tomlPath, alreadyInstalled: true };
  }

  // Find an existing `requires = [` array under `[tool.robotpy]`.
  const reqRe = /(\[tool\.robotpy\][\s\S]*?requires\s*=\s*\[)([\s\S]*?)(\])/m;
  const m = txt.match(reqRe);
  if (m) {
    const newList = m[2].replace(/\s*$/, '') +
      (m[2].trim() ? ',\n  ' : '\n  ') + '"acuity-vision>=0.1"\n';
    txt = txt.replace(reqRe, `$1${newList}$3`);
  } else if (/\[tool\.robotpy\]/.test(txt)) {
    txt = txt.replace(
      /\[tool\.robotpy\][^\n]*\n/,
      (head) => head + 'requires = [\n  "acuity-vision>=0.1"\n]\n'
    );
  } else {
    txt += '\n[tool.robotpy]\nrequires = [\n  "acuity-vision>=0.1"\n]\n';
  }
  fs.writeFileSync(tomlPath, txt);
  return { tomlPath, alreadyInstalled: false };
}

function snippetForLang(lang) {
  if (lang === 'java') {
    return `// In Robot.java
import tech.acuity.AcuityVision;

private final AcuityVision vision = AcuityVision.getInstance();

@Override
public void robotPeriodic() {
  vision.getBestTag().ifPresent(tag -> {
    SmartDashboard.putNumber("acuity/id",         tag.id);
    SmartDashboard.putNumber("acuity/distance_m", tag.distanceMeters);
    SmartDashboard.putNumber("acuity/yaw_deg",    tag.yawDeg);
  });
}`;
  }
  if (lang === 'cpp') {
    return `// In Robot.cpp
#include <acuity/AcuityVision.h>

void Robot::RobotPeriodic() {
  if (auto tag = acuity::AcuityVision::GetInstance().GetBestTag()) {
    frc::SmartDashboard::PutNumber("acuity/id",         tag->id);
    frc::SmartDashboard::PutNumber("acuity/distance_m", tag->distanceMeters);
    frc::SmartDashboard::PutNumber("acuity/yaw_deg",    tag->yawDeg);
  }
}`;
  }
  // python
  return `# In robot.py
import acuity_vision

class MyRobot(wpilib.TimedRobot):
    def robotInit(self):
        self.vision = acuity_vision.AcuityVision()

    def robotPeriodic(self):
        tag = self.vision.get_best_tag()
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
      if (lang === 'java' || lang === 'cpp') {
        const dest = installVendordep(dir);
        return { ok: true, action: 'wrote-vendordep', destPath: dest };
      }
      if (lang === 'python') {
        const r = installPythonDep(dir);
        return {
          ok: true,
          action: r.alreadyInstalled ? 'already-installed' : 'updated-pyproject',
          tomlPath: r.tomlPath,
        };
      }
      return { ok: false, error: `unknown language: ${lang}` };
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
