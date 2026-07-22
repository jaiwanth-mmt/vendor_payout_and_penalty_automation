/** GraphTopologyPanel — investigation graphs collapse block for AgentCockpit. */

import { Eye, EyeOff, Network } from "lucide-react";

import type { GraphTopology } from "../../types/jobs";
import MermaidDiagram from "../MermaidDiagram";

function GraphTopologyPanel({
  topology,
  showGraphs,
  onToggleShowGraphs,
}: {
  topology: GraphTopology;
  showGraphs: boolean;
  onToggleShowGraphs: () => void;
}) {
  if (!topology.case?.mermaid) return null;

  return (
    <div className="agentPanel graphTopologyPanel">
      <div className="agentPanelHeader">
        <div className="graphTopologyTitle">
          <Network size={16} aria-hidden="true" />
          <span>Investigation graphs</span>
        </div>
        <button
          aria-expanded={showGraphs}
          className="ghostButton graphRevealButton"
          type="button"
          onClick={onToggleShowGraphs}
        >
          {showGraphs ? <EyeOff size={16} /> : <Eye size={16} />}
          <span>{showGraphs ? "Hide graphs" : "View graphs"}</span>
        </button>
      </div>
      {!showGraphs ? (
        <p className="graphTopologyHint">
          Case and portfolio LangGraph topology stay collapsed until you need them.
        </p>
      ) : (
        <div className="graphTopologyGrid">
          <div className="graphTopologyCard">
            <div className="agentPanelHeader">
              <span>Case investigation graph</span>
              <strong>{topology.case.nodes?.length ?? 0} nodes</strong>
            </div>
            <MermaidDiagram chart={topology.case.mermaid} className="mermaidDiagram" />
          </div>
          {topology.portfolio?.mermaid && (
            <div className="graphTopologyCard">
              <div className="agentPanelHeader">
                <span>Portfolio graph</span>
                <strong>{topology.portfolio.nodes?.length ?? 0} nodes</strong>
              </div>
              <MermaidDiagram chart={topology.portfolio.mermaid} className="mermaidDiagram" />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default GraphTopologyPanel;
