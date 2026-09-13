import type { CSSProperties } from "react";
import {
  useAppearanceTheme,
  type JaceThemeDefinition,
} from "../shell/appearanceTheme";

function ThemePreview(props: {
  theme: JaceThemeDefinition;
}) {
  const style = {
    "--appearance-preview-bg":
      props.theme.preview.background,
    "--appearance-preview-panel":
      props.theme.preview.panel,
    "--appearance-preview-accent":
      props.theme.preview.accent,
    "--appearance-preview-secondary":
      props.theme.preview.secondary,
    "--appearance-preview-text":
      props.theme.preview.text,
  } as CSSProperties;

  return (
    <span
      className="appearance-theme-preview"
      style={style}
      aria-hidden="true"
    >
      <i className="appearance-preview-topbar" />
      <i className="appearance-preview-core" />
      <i className="appearance-preview-panel one" />
      <i className="appearance-preview-panel two" />
      <b />
    </span>
  );
}

export function AppearanceSettings() {
  const appearance = useAppearanceTheme();

  return (
    <section className="settings-card full-card appearance-settings-card">
      <div className="settings-card-heading">
        <div>
          <span className="section-kicker">
            Appearance
          </span>
          <h2>Jace theme</h2>
        </div>
        <span className="settings-icon">◈</span>
      </div>

      <p className="field-help">
        Choose a visual palette for the Command Center,
        full-page Settings, Workspace, Agent Office,
        Jace Core and detached windows. Theme changes are
        local to this computer and apply to every open
        Jace window immediately.
      </p>

      <div className="appearance-theme-grid">
        {appearance.definitions.map((theme) => {
          const active =
            appearance.theme === theme.id;

          return (
            <button
              type="button"
              key={theme.id}
              className={`appearance-theme-option ${
                active ? "active" : ""
              }`}
              onClick={() =>
                appearance.setTheme(theme.id)
              }
              aria-pressed={active}
            >
              <ThemePreview theme={theme} />
              <span className="appearance-theme-copy">
                <strong>{theme.name}</strong>
                <small>{theme.description}</small>
              </span>
              <span className="appearance-theme-state">
                {active ? "ACTIVE" : ""}
              </span>
            </button>
          );
        })}
      </div>

      <div className="info-box appearance-theme-info">
        <strong>
          {appearance.definition.name} active
        </strong>
        <span>
          This is a semantic theme layer rather than a
          separate stylesheet, so future Jace screens can
          inherit the same surface, border, text and signal
          colours automatically.
        </span>
      </div>
    </section>
  );
}
