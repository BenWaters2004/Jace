import { useEffect, useState } from "react";
import { getHealth, getSettings } from "../api";
import { AgentOffice } from "./AgentOffice";
import { DetachedWindowFrame } from "./DetachedWindowFrame";
import { JaceCore } from "./JaceCore";
import { useRuntimeEvents } from "./runtime";

type LightweightProfile = {
  assistantName: string;
  model: string;
  online: boolean;
};

export function DetachedPanelApp(props: { panel: "core" | "office" }) {
  const [profile, setProfile] = useState<LightweightProfile>({
    assistantName: "Jace",
    model: "",
    online: false,
  });

  useEffect(() => {
    let disposed = false;

    void Promise.all([getSettings(), getHealth()])
      .then(([settings, health]) => {
        if (disposed) return;
        setProfile({
          assistantName: settings.assistant_name || "Jace",
          model: settings.default_model || "",
          online: Boolean(health.ollama_connected),
        });
      })
      .catch(() => {
        if (!disposed) {
          setProfile((current) => ({ ...current, online: false }));
        }
      });

    return () => {
      disposed = true;
    };
  }, []);

  const runtime = useRuntimeEvents(profile.online ? "idle" : "offline");

  if (props.panel === "core") {
    return (
      <DetachedWindowFrame title="Jace Core" subtitle="Live runtime visualizer">
        <JaceCore
          name={profile.assistantName}
          state={
            runtime.connected
              ? runtime.state
              : profile.online
                ? "idle"
                : "offline"
          }
          model={profile.model}
          runtimeConnected={runtime.connected}
          amplitude={0}
          onExpand={() => undefined}
          controls={<span className="detached-panel-inline-spacer" />}
        />
      </DetachedWindowFrame>
    );
  }

  return (
    <DetachedWindowFrame
      title="Agent Office"
      subtitle="Real specialist workers and executor state"
    >
      <AgentOffice
        activities={[]}
        onExpand={() => undefined}
        controls={<span className="detached-panel-inline-spacer" />}
      />
    </DetachedWindowFrame>
  );
}
