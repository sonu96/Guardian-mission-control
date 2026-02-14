import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";
import { authTables } from "@convex-dev/auth/server";
import { optionsTables } from "./options-schema";

export default defineSchema({
	...authTables,
	...optionsTables,
		agents: defineTable({
			name: v.string(),
			role: v.string(),
		status: v.union(
			v.literal("idle"),
			v.literal("active"),
			v.literal("blocked"),
		),
		level: v.union(v.literal("LEAD"), v.literal("INT"), v.literal("SPC")),
		avatar: v.string(),
		currentTaskId: v.optional(v.id("tasks")),
		sessionKey: v.optional(v.string()),
		systemPrompt: v.optional(v.string()),
		character: v.optional(v.string()),
			lore: v.optional(v.string()),
			orgId: v.optional(v.string()),
			workspaceId: v.optional(v.string()),
			tenantId: v.optional(v.string()),
		}).index("by_tenant", ["tenantId"]),
		tasks: defineTable({
		title: v.string(),
		description: v.string(),
		status: v.union(
			v.literal("inbox"),
			v.literal("assigned"),
			v.literal("in_progress"),
			v.literal("review"),
			v.literal("done"),
			v.literal("archived"),
		),
		assigneeIds: v.array(v.id("agents")),
		tags: v.array(v.string()),
		borderColor: v.optional(v.string()),
		sessionKey: v.optional(v.string()),
		openclawRunId: v.optional(v.string()),
		startedAt: v.optional(v.number()),
			usedCodingTools: v.optional(v.boolean()),
			orgId: v.optional(v.string()),
			workspaceId: v.optional(v.string()),
			tenantId: v.optional(v.string()),
		}).index("by_tenant", ["tenantId"]),
		messages: defineTable({
		taskId: v.id("tasks"),
		fromAgentId: v.id("agents"),
			content: v.string(),
			attachments: v.array(v.id("documents")),
			orgId: v.optional(v.string()),
			workspaceId: v.optional(v.string()),
			tenantId: v.optional(v.string()),
		})
			.index("by_tenant", ["tenantId"])
			.index("by_tenant_task", ["tenantId", "taskId"]),
		activities: defineTable({
			type: v.string(),
			agentId: v.id("agents"),
			message: v.string(),
			targetId: v.optional(v.id("tasks")),
			orgId: v.optional(v.string()),
			workspaceId: v.optional(v.string()),
			tenantId: v.optional(v.string()),
		})
			.index("by_tenant", ["tenantId"])
			.index("by_tenant_target", ["tenantId", "targetId"]),
		documents: defineTable({
		title: v.string(),
		content: v.string(),
		type: v.string(),
		path: v.optional(v.string()),
			taskId: v.optional(v.id("tasks")),
			createdByAgentId: v.optional(v.id("agents")),
			messageId: v.optional(v.id("messages")),
			orgId: v.optional(v.string()),
			workspaceId: v.optional(v.string()),
			tenantId: v.optional(v.string()),
		})
			.index("by_tenant", ["tenantId"])
			.index("by_tenant_task", ["tenantId", "taskId"]),
		notifications: defineTable({
			mentionedAgentId: v.id("agents"),
			content: v.string(),
			delivered: v.boolean(),
			orgId: v.optional(v.string()),
			workspaceId: v.optional(v.string()),
			tenantId: v.optional(v.string()),
		}),
	apiTokens: defineTable({
		tokenHash: v.string(),
		tokenPrefix: v.string(),
		tenantId: v.optional(v.string()),
		orgId: v.optional(v.string()),
		name: v.optional(v.string()),
		createdAt: v.number(),
		lastUsedAt: v.optional(v.number()),
		revokedAt: v.optional(v.number()),
	})
		.index("by_tokenHash", ["tokenHash"])
		.index("by_tenant", ["tenantId"]),
	tenantSettings: defineTable({
		tenantId: v.string(),
		retentionDays: v.number(),
		onboardingCompletedAt: v.optional(v.number()),
		createdAt: v.number(),
		updatedAt: v.number(),
	}).index("by_tenant", ["tenantId"]),
	rateLimits: defineTable({
		tenantId: v.optional(v.string()),
		orgId: v.optional(v.string()),
		windowStartMs: v.number(),
		count: v.number(),
	}).index("by_tenant", ["tenantId"]),
});
