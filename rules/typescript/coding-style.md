# TS-CODING-STYLE | extends common/coding-style | for-AI-parsing

<rules>

IMMUTABILITY:
  pattern: spread operator for updates → { ...original, field: newValue }
  banned: in-place mutation(obj.field = value)

ERROR-HANDLING:
  pattern: async/await + try-catch
  catch: log error + throw new Error(user-friendly message)

INPUT-VALIDATION:
  tool: Zod
  pattern: z.object({ ... }).parse(input)

CONSOLE-LOG:
  banned: production code
  action: use proper logging libraries
  detection: see hooks

</rules>
