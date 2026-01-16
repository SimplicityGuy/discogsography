# 🤝 Contributing Guide

<div align="center">

**How to contribute to Discogsography**

[🏠 Back to Main](../README.md) | [📚 Documentation Index](README.md) | [👨‍💻 Development Guide](development.md)

</div>

## Welcome Contributors!

We're thrilled that you're interested in contributing to Discogsography! This document will guide you through the contribution process.

## 🌟 Ways to Contribute

There are many ways to contribute to Discogsography:

### Code Contributions

- 🐛 **Fix bugs** - Help resolve issues
- ✨ **Add features** - Implement new functionality
- ⚡ **Improve performance** - Optimize existing code
- 🔐 **Enhance security** - Find and fix vulnerabilities
- 🧪 **Write tests** - Increase code coverage

### Documentation

- 📝 **Improve docs** - Fix typos, clarify explanations
- 📚 **Write tutorials** - Help others learn the system
- 🎨 **Create diagrams** - Visualize architecture
- 🌐 **Translate** - Make docs accessible in other languages

### Community

- 💬 **Answer questions** - Help others in discussions
- 🐛 **Report bugs** - File detailed bug reports
- 💡 **Suggest features** - Share your ideas
- 🎉 **Share your use case** - Inspire others

## 📋 Contribution Process

### 1. Find or Create an Issue

**Before starting work:**

- Check [existing issues](https://github.com/SimplicityGuy/discogsography/issues)
- Comment on the issue you want to work on
- Wait for maintainer approval (for large changes)
- Create a new issue if needed

**Good first issues:**

- Look for `good first issue` label
- Look for `help wanted` label
- Start small to learn the codebase

### 2. Fork & Clone

```bash
# Fork the repository on GitHub
# Then clone your fork

git clone https://github.com/YOUR_USERNAME/discogsography.git
cd discogsography

# Add upstream remote
git remote add upstream https://github.com/SimplicityGuy/discogsography.git
```

### 3. Set Up Development Environment

```bash
# Install uv (package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install just (task runner)
brew install just  # macOS
# or: cargo install just

# Install all dependencies
just install

# Set up pre-commit hooks
just init

# Start infrastructure services
docker-compose up -d neo4j postgres rabbitmq redis
```

See [Development Guide](development.md) for complete setup instructions.

### 4. Create a Feature Branch

```bash
# Update your fork
git checkout main
git pull upstream main

# Create feature branch
git checkout -b feature/your-feature-name

# Or for bug fixes
git checkout -b fix/bug-description
```

**Branch naming conventions:**

- `feature/` - New features
- `fix/` - Bug fixes
- `docs/` - Documentation changes
- `refactor/` - Code refactoring
- `test/` - Test additions/improvements
- `chore/` - Maintenance tasks

### 5. Make Your Changes

**Follow these guidelines:**

#### Code Style

- Use **type hints** for all function parameters and returns
- Write **docstrings** for public functions and classes
- Follow **PEP 8** style guide (enforced by ruff)
- Use **88-character line length** (Black standard)
- Add **emoji-prefixed logging** (see [Emoji Guide](emoji-guide.md))

#### Testing

- Add **unit tests** for new code
- Maintain **>80% code coverage**
- Update **integration tests** if needed
- Add **E2E tests** for new UI features

#### Documentation

- Update **README.md** if needed
- Add/update **docstrings**
- Update relevant **docs/** files
- Include **code examples** where helpful

#### Security

- Never **log sensitive data** (passwords, tokens, PII)
- Use **parameterized queries** (prevent SQL injection)
- **Scan for vulnerabilities** (`just security`)
- Follow **security best practices**

### 6. Test Your Changes

```bash
# Run linters
just lint

# Format code
just format

# Type check
just typecheck

# Security scan
just security

# Run tests
just test

# Run tests with coverage
just test-cov

# Run E2E tests (if applicable)
just test-e2e

# Or run everything
uv run pre-commit run --all-files
```

**All checks must pass before submitting a PR!**

### 7. Commit Your Changes

```bash
# Stage changes
git add .

# Commit with conventional commit message
git commit -m "feat: add amazing feature"
```

**Commit message format:**

```
<type>: <description>

[optional body]

[optional footer]
```

**Types:**

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting)
- `refactor`: Code refactoring
- `test`: Test additions/changes
- `chore`: Maintenance tasks

**Examples:**

```bash
git commit -m "feat: add artist similarity search"
git commit -m "fix: correct Neo4j connection retry logic"
git commit -m "docs: update quick start guide"
git commit -m "test: add tests for discovery service"
```

### 8. Push to Your Fork

```bash
# Push your branch
git push origin feature/your-feature-name
```

### 9. Create Pull Request

1. Go to your fork on GitHub
1. Click "New pull request"
1. Select your feature branch
1. Fill out the PR template:
   - Clear title
   - Description of changes
   - Related issue number
   - Screenshots (if UI changes)
   - Testing performed
1. Submit the pull request

**PR Title Format:**

```
<type>: <short description>
```

Examples:

- `feat: add artist similarity search`
- `fix: correct database connection retry logic`
- `docs: update configuration guide`

## ✅ Pull Request Checklist

Before submitting, ensure:

- [ ] Code follows style guide (ruff, black, mypy pass)
- [ ] All tests pass (`just test`)
- [ ] E2E tests pass if applicable (`just test-e2e`)
- [ ] Security scan passes (`just security`)
- [ ] Code coverage maintained or improved
- [ ] Type hints are complete
- [ ] Docstrings are added/updated
- [ ] Documentation is updated
- [ ] Commit messages follow conventions
- [ ] Pre-commit hooks are installed and pass
- [ ] Changes are tested locally
- [ ] No merge conflicts with main branch

## 🔍 Code Review Process

### What to Expect

1. **Initial Review**: Maintainer will review within 1-3 days
1. **Feedback**: You may receive requests for changes
1. **Discussion**: We may discuss implementation approaches
1. **Approval**: Once approved, PR will be merged

### Making Changes

```bash
# Make requested changes
git add .
git commit -m "refactor: address review feedback"
git push origin feature/your-feature-name
```

### Keep Your PR Updated

```bash
# Sync with upstream main
git checkout main
git pull upstream main
git checkout feature/your-feature-name
git merge main

# Resolve any conflicts
# Then push
git push origin feature/your-feature-name
```

## 📝 Development Standards

### Python Code Quality

**Tools we use:**

- **ruff**: Fast linting and formatting
- **mypy**: Static type checking
- **bandit**: Security vulnerability scanning
- **pytest**: Testing framework
- **pre-commit**: Git hooks for quality

**Run quality checks:**

```bash
# All checks
just lint
just format
just typecheck
just security
just test

# Or all at once
uv run pre-commit run --all-files
```

### Testing Standards

**Coverage requirements:**

- Minimum **80% code coverage**
- All new code **must have tests**
- Update tests for **modified code**

**Test types:**

- **Unit tests**: Test individual functions
- **Integration tests**: Test service interactions
- **E2E tests**: Test user workflows (Playwright)

See [Testing Guide](testing-guide.md) for details.

### Documentation Standards

**File naming:**

- Use **lowercase with hyphens**: `new-feature-guide.md`
- Add to `docs/` directory
- Update `docs/README.md` index

**Structure:**

- **Header** with title and navigation
- **Overview** section
- **Clear examples** with code blocks
- **Last Updated** date

**Diagrams:**

- Use **Mermaid** for diagrams
- Follow existing diagram style
- Include alt text for accessibility

## 🐛 Bug Reports

### Before Reporting

1. **Search existing issues** - bug may already be reported
1. **Try latest version** - bug may be fixed
1. **Reproduce the bug** - ensure it's consistent
1. **Gather information** - logs, environment, steps

### Creating a Bug Report

Use the bug report template:

```markdown
**Describe the bug**
A clear description of what the bug is.

**To Reproduce**
Steps to reproduce:
1. Go to '...'
2. Click on '....'
3. See error

**Expected behavior**
What you expected to happen.

**Screenshots**
If applicable, add screenshots.

**Environment:**
 - OS: [e.g., macOS 13]
 - Python version: [e.g., 3.13.1]
 - Docker version: [e.g., 24.0.0]

**Logs**
```

Paste relevant logs here

```

**Additional context**
Any other information about the problem.
```

## 💡 Feature Requests

### Before Requesting

1. **Search existing issues** - feature may be planned
1. **Check roadmap** - might be on the roadmap
1. **Consider alternatives** - maybe there's another way

### Creating a Feature Request

Use the feature request template:

```markdown
**Is your feature request related to a problem?**
A clear description of what the problem is.

**Describe the solution you'd like**
A clear description of what you want to happen.

**Describe alternatives you've considered**
Alternative solutions or features you've considered.

**Additional context**
Any other context or screenshots.

**Would you be willing to implement this?**
Yes/No - helps us prioritize!
```

## ❓ Questions and Discussions

Have a question? Use [GitHub Discussions](https://github.com/SimplicityGuy/discogsography/discussions):

- **Q&A**: Ask questions
- **Ideas**: Brainstorm features
- **Show and tell**: Share your use case
- **General**: Other discussions

**Please don't:**

- Open issues for questions
- Email maintainers directly
- Use PR comments for discussions

## 🏆 Recognition

We recognize our contributors!

- **Contributors** are listed in README
- **Significant contributions** get special mention
- **Regular contributors** may become maintainers

## 📜 Code of Conduct

### Our Standards

We are committed to providing a welcoming and inclusive environment:

**Positive behaviors:**

- Using welcoming and inclusive language
- Being respectful of differing viewpoints
- Gracefully accepting constructive criticism
- Focusing on what is best for the community
- Showing empathy towards other community members

**Unacceptable behaviors:**

- Trolling, insulting/derogatory comments, and personal or political attacks
- Public or private harassment
- Publishing others' private information without explicit permission
- Other conduct which could reasonably be considered inappropriate

### Enforcement

Violations of the code of conduct may result in:

1. **Warning**: First offense
1. **Temporary ban**: Repeated offenses
1. **Permanent ban**: Serious or continued violations

## 📚 Resources

### Documentation

- [Development Guide](development.md) - Complete dev setup
- [Testing Guide](testing-guide.md) - Testing strategies
- [Logging Guide](logging-guide.md) - Logging standards
- [Emoji Guide](emoji-guide.md) - Emoji conventions
- [GitHub Actions Guide](github-actions-guide.md) - CI/CD

### Tools

- [uv Documentation](https://github.com/astral-sh/uv)
- [ruff Documentation](https://github.com/astral-sh/ruff)
- [pytest Documentation](https://docs.pytest.org/)
- [Playwright Documentation](https://playwright.dev/python/)

### Community

- [GitHub Issues](https://github.com/SimplicityGuy/discogsography/issues)
- [GitHub Discussions](https://github.com/SimplicityGuy/discogsography/discussions)
- [Pull Requests](https://github.com/SimplicityGuy/discogsography/pulls)

## 💬 Get Help

Need help contributing?

1. **Read the docs** - Start with [Development Guide](development.md)
1. **Check discussions** - Someone may have asked already
1. **Ask in discussions** - We're happy to help!
1. **Join our community** - Connect with other contributors

## 🙏 Thank You!

Thank you for contributing to Discogsography! Every contribution, no matter how small, helps make this project better.

We appreciate your time and effort! 🎉

______________________________________________________________________

**Last Updated**: 2025-01-15
