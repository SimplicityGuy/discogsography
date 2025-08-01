Quick initialization with auto-confirmation.

Arguments: $ARGUMENTS

Initialize a Task Master project without prompts, accepting all defaults.

## Quick Setup

```bash
task-master init -y
```

## What It Does

1. Creates `.taskmaster/` directory structure
1. Initializes empty `tasks.json`
1. Sets up default configuration
1. Uses directory name as project name
1. Skips all confirmation prompts

## Smart Defaults

- Project name: Current directory name
- Description: "Task Master Project"
- Model config: Existing environment vars
- Task structure: Standard format

## Next Steps

After quick init:

1. Configure AI models if needed:

   ```
   /project:tm/models/setup
   ```

1. Parse PRD if available:

   ```
   /project:tm/parse-prd <file>
   ```

1. Or create first task:

   ```
   /project:tm/add-task create initial setup
   ```

Perfect for rapid project setup!
