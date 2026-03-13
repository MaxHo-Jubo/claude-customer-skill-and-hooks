# TS-PATTERNS | extends common/patterns | for-AI-parsing

<rules>

API-RESPONSE:
  interface: "ApiResponse<T> { success: boolean; data?: T; error?: string; meta?: { total, page, limit } }"

CUSTOM-HOOK:
  pattern: useDebounce<T>(value, delay) → useState + useEffect + setTimeout
  convention: use-prefix for all custom hooks

REPOSITORY:
  interface: "Repository<T> { findAll(filters?): Promise<T[]>; findById(id): Promise<T|null>; create(data): Promise<T>; update(id, data): Promise<T>; delete(id): Promise<void> }"

</rules>
