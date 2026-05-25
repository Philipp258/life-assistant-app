import { ChoiceCard } from "@/components/assistant-ui/choice-card";
import {
  KnowledgeCreatedCard,
  KnowledgeUpdatedCard,
} from "@/components/assistant-ui/knowledge-saved-card";
import { MarkdownText } from "@/components/assistant-ui/markdown-text";
import { Reasoning, ReasoningGroup } from "@/components/assistant-ui/reasoning";
import { TaskCreatedCard } from "@/components/assistant-ui/task-created-card";
import { ToolFallback } from "@/components/assistant-ui/tool-fallback";

/**
 * Component map passed to `MessagePrimitive.Parts` for assistant messages.
 *
 * Shared between the production chat thread and the task detail activity
 * thread so markdown / reasoning / tool / first-class tool cards render the
 * same way in both surfaces. Outer message chrome differs; the content
 * renderers do not.
 */
export const assistantMessagePartComponents = {
  Text: MarkdownText,
  Reasoning,
  ReasoningGroup,
  tools: {
    by_name: {
      create_task: TaskCreatedCard,
      create_knowledge: KnowledgeCreatedCard,
      update_knowledge: KnowledgeUpdatedCard,
      save_knowledge: KnowledgeUpdatedCard,
      ask_user_choice: ChoiceCard,
    },
    Fallback: ToolFallback,
  },
} as const;
