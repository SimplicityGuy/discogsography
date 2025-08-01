Mark a task as completed.

Arguments: $ARGUMENTS (task ID)

## Completing a Task

This command validates task completion and updates project state intelligently.

## Pre-Completion Checks

1. Verify test strategy was followed
1. Check if all subtasks are complete
1. Validate acceptance criteria met
1. Ensure code is committed

## Execution

```bash
task-master set-status --id=$ARGUMENTS --status=done
```

## Post-Completion Actions

1. **Update Dependencies**

   - Identify newly unblocked tasks
   - Update sprint progress
   - Recalculate project timeline

1. **Documentation**

   - Generate completion summary
   - Update CLAUDE.md with learnings
   - Log implementation approach

1. **Next Steps**

   - Show newly available tasks
   - Suggest logical next task
   - Update velocity metrics

## Celebration & Learning

- Show impact of completion
- Display unblocked work
- Recognize achievement
- Capture lessons learned
