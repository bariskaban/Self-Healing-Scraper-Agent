import { z } from "zod";

const iso = z.string().refine((s) => !Number.isNaN(Date.parse(s)), "invalid time");

export const usageSchema = z.object({
  inputTokens: z.number().nonnegative(),
  outputTokens: z.number().nonnegative(),
  cachedInputTokens: z.number().nonnegative().optional(),
  reasoningTokens: z.number().nonnegative().optional(),
  costUsd: z.number().nonnegative(),
  costEur: z.number().nonnegative(),
});

export const settingsSchema = z.object({
  attachTimeLimitMinutes: z.number().int().positive(),
  ignoreRobotsTxt: z.boolean(),
});

export const portalStateSchema = z.enum(["failed", "healing", "integrating", "serving"]);
/** A state this page does not know reads as failed instead of taking the whole page offline. */
const lenientState = portalStateSchema.catch("failed");
const runKind = z.enum(["read", "repair"]);
const runResult = z.enum(["ok", "failed"]).nullable();

export const portalSchema = z.object({
  id: z.string().min(1),
  url: z.string(),
  state: lenientState,
  reason: z.string().catch(""),
  tenderCount: z.number().int().nonnegative(),
  lastSuccessAt: iso.nullable(),
  cause: z.string().nullable().catch(null),
  fingerprint: z.string().nullable(),
  timezone: z.string().nullable(),
  recipeVersion: z.number().nullable(),
  reusedFrom: z.string().nullable().optional(),
  nextReadAt: iso.nullable(),
  lastRun: z.object({ id: z.string(), kind: runKind, result: runResult }).nullable(),
  recentReads: z.array(runResult),
  deliveryTrend: z.array(z.number()),
  readsLastHour: z.number().int().nonnegative(),
  usage: usageSchema.nullable(),
});

export const dashboardSchema = z.object({
  asOf: iso,
  eurPerUsd: z.number().positive(),
  settings: settingsSchema,
  portals: z.array(portalSchema),
});

export const checkSchema = z.object({
  name: z.string(),
  passed: z.boolean(),
  severity: z.enum(["info", "warn", "fail", "block"]),
  message: z.string(),
  observed: z.unknown().optional(),
  expected: z.unknown().optional(),
});

export const stepSchema = z.object({
  seq: z.number(),
  at: iso,
  kind: z.enum(["tool", "llm", "note", "decision"]),
  name: z.string(),
  summary: z.string(),
  durationMs: z.number().nonnegative().nullable(),
  usage: usageSchema.nullish(),
});

export const runSchema = z.object({
  id: z.string().min(1),
  kind: runKind,
  trigger: z.enum(["attach", "schedule", "refresh", "recheck", "heal"]),
  startedAt: iso,
  finishedAt: iso.nullable(),
  result: runResult,
  summary: z.string(),
  recipeVersion: z.number().optional(),
  publishedCount: z.number().int().nonnegative().optional(),
  stats: z.record(z.union([z.number(), z.string(), z.boolean(), z.null()])).optional(),
  modelCalls: z.number().int().nonnegative(),
  usage: usageSchema.nullish(),
  checks: z.array(checkSchema).optional(),
  steps: z.array(stepSchema).optional(),
  recipeChange: z
    .object({
      from: z.number(),
      to: z.number(),
      rationale: z.string(),
      changedParts: z.array(z.string()),
    })
    .optional(),
});

export const timelineSchema = z.array(runSchema);

export const documentSchema = z.object({
  fileName: z.string(),
  sizeBytes: z.number().nonnegative().nullable(),
  sha256: z.string().nullable(),
  path: z.string().nullable(),
});

/**
 * Mirrors TenderOut in app/models.py: the required fields are always present but null when the
 * portal does not show them; the optional ones are left out when empty. publicationDate is a plain
 * date (2026-12-09), the other times carry an offset. Keys not listed here (contractNature,
 * cpvCodes, placeOfPerformance) are not rendered and are dropped, never rejected.
 */
export const tenderSchema = z.object({
  id: z.string(),
  url: z.string().nullable(),
  title: z.string().nullable(),
  buyerName: z.string().nullable(),
  publicationDate: iso.nullable(),
  submissionDeadline: iso.nullable(),
  status: z.enum(["open", "closed", "withdrawn"]),
  documents: z.array(documentSchema).nullable(),
  lastChangedAt: iso,
  referenceNumber: z.string().nullish(),
  description: z.string().nullish(),
  procedureType: z.string().nullish(),
});

export const tendersSchema = z.array(tenderSchema);

/** One row of the paged list: a tender without its files, with only their count. */
export const tenderItemSchema = tenderSchema.omit({ documents: true }).extend({
  documentCount: z.number().int().nonnegative().nullable(),
});

/** GET /api/portals/{id}/tenders?limit&offset. `next` is the offset of the next page, null at the end. */
export const tenderPageSchema = z.object({
  total: z.number().int().nonnegative(),
  offset: z.number().int().nonnegative(),
  limit: z.number().int().positive(),
  next: z.number().int().nonnegative().nullable(),
  items: z.array(tenderItemSchema),
});

/** GET /api/portals/{id}/tenders/{tenderId}: one full tender (TenderOut) with its files. */
export const singleTenderSchema = tenderSchema;

/** PortalOut: one entry of the public GET /portals. The contract routes carry nothing else about a portal. */
export const contractPortalSchema = z.object({
  id: z.string().min(1),
  url: z.string(),
  state: lenientState,
  reason: z.string().catch(""),
  tenderCount: z.number().int().nonnegative(),
  lastSuccessAt: iso.nullable(),
  cause: z.string().nullish().catch(null),
});
export const contractPortalsSchema = z.array(contractPortalSchema);

/** RunOut: one entry of the public GET /portals/{id}/runs, oldest first. */
export const contractRunSchema = z.object({
  id: z.string().min(1),
  kind: runKind,
  startedAt: iso,
  finishedAt: iso.nullable(),
  result: runResult,
});
export const contractRunsSchema = z.array(contractRunSchema);

/** 201 answer of POST /portals. The same address always gets the same id. */
export const createdIdSchema = z.object({ id: z.string().min(1) });
