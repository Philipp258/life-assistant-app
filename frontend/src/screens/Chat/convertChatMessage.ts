// Backend snapshots are AI-SDK `UIMessage`s. The chat store keeps this
// wire shape as its source data and the external-store runtime converts
// it to assistant-ui messages at the edge.

import type { UIMessage } from "ai";

export type WireMessage = UIMessage & {
  __optimistic?: boolean;
  __draft?: boolean;
};
