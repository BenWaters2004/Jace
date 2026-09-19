import {
  useState,
  type ComponentProps,
} from "react";
import { ComputerHub } from "./ComputerHub";
import "../runtimeSurface.css";
import { RuntimeSurface } from "./RuntimeSurface";

type ComputerHubProps = ComponentProps<typeof ComputerHub>;
type ComputerRuntimeTab = "workspaces" | "runtime";

export function ComputerRuntimeHub(
  props: ComputerHubProps,
) {
  const [tab, setTab] = useState<ComputerRuntimeTab>(
    "workspaces",
  );

  return (
    <section className="computer-runtime-hub">
      <header className="computer-runtime-tabs">
        <button
          type="button"
          className={tab === "workspaces" ? "active" : ""}
          onClick={() => setTab("workspaces")}
        >
          Workspaces
        </button>
        <button
          type="button"
          className={tab === "runtime" ? "active" : ""}
          onClick={() => setTab("runtime")}
        >
          Runtime
        </button>
      </header>

      <div className="computer-runtime-body">
        {tab === "workspaces" ? (
          <ComputerHub {...props} />
        ) : (
          <RuntimeSurface />
        )}
      </div>
    </section>
  );
}
