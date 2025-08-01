Cancel a task permanently.

Arguments: $ARGUMENTS (task ID)

## Cancelling a Task

This status indicates a task is no longer needed and won't be completed.

## Valid Reasons for Cancellation

- Requirements changed
- Feature deprecated
- Duplicate of another task
- Strategic pivot
- Technical approach invalidated

## Pre-Cancellation Checks

1. Confirm no critical dependencies
1. Check for partial implementation
1. Verify cancellation rationale
1. Document lessons learned

## Execution

```bash
task-master set-status --id=$ARGUMENTS --status=cancelled
```

## Cancellation Impact

When cancelling:

1. **Dependency Updates**

   - Notify dependent tasks
   - Update project scope
   - Recalculate timelines

1. **Clean-up Actions**

   - Remove related branches
   - Archive any work done
   - Update documentation
   - Close related issues

1. **Learning Capture**

   - Document why cancelled
   - Note what was learned
   - Update estimation models
   - Prevent future duplicates

## Historical Preservation

- Keep for reference
- Tag with cancellation reason
- Link to replacement if any
- Maintain audit trail
