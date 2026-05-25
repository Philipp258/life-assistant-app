import { useNavigate, useParams } from "react-router-dom";

import { useGoBack } from "@/lib/useGoBack";

import { CoreMemoryEditor } from "./CoreMemoryEditor";
import type { CoreMemoryName } from "./knowledgeApi";
import { KnowledgeEditor } from "./KnowledgeEditor";
import { SkillView } from "./SkillView";

export function KnowledgeDetailRoute() {
  const params = useParams();
  const navigate = useNavigate();
  const goBack = useGoBack("/know");
  const path = params["*"] ?? "";
  // Deletion has no previous entry to return to; jump to the list and
  // refresh state by mounting the screen fresh.
  const onDeleted = () => navigate("/know", { replace: true });
  return <KnowledgeEditor path={path} onBack={goBack} onDeleted={onDeleted} />;
}

const CORE_NAMES: ReadonlySet<string> = new Set(["about_user", "behavior"]);

export function CoreMemoryRoute() {
  const params = useParams<{ name: string }>();
  const goBack = useGoBack("/know");
  const name = params.name ?? "";
  if (!CORE_NAMES.has(name)) {
    // Unknown core memory key — send the user back to the list rather
    // than crashing the editor on a bad URL.
    return <BackToKnowledge message={`Unknown core memory: ${name}`} />;
  }
  return <CoreMemoryEditor name={name as CoreMemoryName} onBack={goBack} />;
}

export function SkillRoute() {
  const params = useParams<{ name: string }>();
  const goBack = useGoBack("/know");
  const name = params.name ?? "";
  if (!name) {
    return <BackToKnowledge message="Missing skill name" />;
  }
  return <SkillView name={name} onBack={goBack} />;
}

function BackToKnowledge({ message }: { message: string }) {
  const goBack = useGoBack("/know");
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
      <div className="text-sm text-red-500">{message}</div>
      <button
        type="button"
        onClick={goBack}
        className="text-xs text-life-ink-3 underline"
      >
        Back
      </button>
    </div>
  );
}
