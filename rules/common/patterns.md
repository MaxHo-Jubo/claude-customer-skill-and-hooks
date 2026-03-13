# PATTERNS | for-AI-parsing

<rules>

SKELETON-PROJECT:
  trigger: implementing new functionality
  flow: search battle-tested skeletons → parallel agents evaluate(security/extensibility/relevance/plan) → clone best → iterate

REPOSITORY-PATTERN:
  interface: findAll/findById/create/update/delete
  concrete: handles storage details(db/API/file)
  dependency: business logic → abstract interface(not storage)
  benefit: swap data sources + mock testing

API-RESPONSE:
  envelope:
    success: boolean
    data: nullable(on error)
    error: nullable(on success)
    meta: total/page/limit(paginated responses)

</rules>
