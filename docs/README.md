# 📚 Discogsography Documentation

<div align="center">

**Comprehensive guides and documentation for the Discogsography platform**

[🏠 Back to Main](../README.md) | [🤖 Claude Guide](../CLAUDE.md) | [📋 Emoji Guide](emoji-guide.md)

</div>

## 📖 Documentation Index

### 🚀 Getting Started

| Document                                     | Description                                             |
| -------------------------------------------- | ------------------------------------------------------- |
| **[Quick Start Guide](quick-start.md)**      | ⚡ Get Discogsography running in minutes                |
| **[Configuration Guide](configuration.md)**  | ⚙️ Complete environment variable and settings reference |
| **[Architecture Overview](architecture.md)** | 🏛️ System architecture, components, and data flow       |

### 📊 Core Guides

| Document                                        | Description                                           |
| ----------------------------------------------- | ----------------------------------------------------- |
| **[Database Schema](database-schema.md)**       | 🗄️ Complete Neo4j and PostgreSQL schema documentation |
| **[Usage Examples](usage-examples.md)**         | 💡 Query examples for Neo4j and PostgreSQL            |
| **[Monitoring Guide](monitoring.md)**           | 📊 Real-time monitoring, debugging, and operations    |
| **[Troubleshooting Guide](troubleshooting.md)** | 🔧 Common issues and solutions                        |

### 👨‍💻 Development

| Document                                                      | Description                                        |
| ------------------------------------------------------------- | -------------------------------------------------- |
| **[Development Guide](development.md)**                       | 💻 Complete developer setup and workflow guide     |
| **[Contributing Guide](contributing.md)**                     | 🤝 How to contribute to the project                |
| **[Testing Guide](testing-guide.md)**                         | 🧪 Comprehensive testing strategies and patterns   |
| **[Logging Guide](logging-guide.md)**                         | 📊 Complete logging configuration and best practices |
| **[Python Version Management](python-version-management.md)** | 🐍 Managing Python 3.13+ across the project        |

### 🚀 Operations & Infrastructure

| Document                                            | Description                                      |
| --------------------------------------------------- | ------------------------------------------------ |
| **[Docker Security](docker-security.md)**           | 🔒 Container hardening & security practices      |
| **[Dockerfile Standards](dockerfile-standards.md)** | 🐋 Best practices for writing Dockerfiles        |
| **[Database Resilience](database-resilience.md)**   | 💾 Database connection patterns & error handling |
| **[Performance Guide](performance-guide.md)**       | ⚡ Performance optimization strategies           |
| **[Maintenance Guide](maintenance.md)**             | 🔧 Keeping the system up-to-date and healthy     |


### ⚙️ Workflow & Automation

| Document                                            | Description                                          |
| --------------------------------------------------- | ---------------------------------------------------- |
| **[GitHub Actions Guide](github-actions-guide.md)** | 🔄 CI/CD workflows, automation & best practices      |
| **[Task Automation](task-automation.md)**           | ⚡ Complete taskipy command reference                |
| **[Monorepo Guide](monorepo-guide.md)**             | 📦 Managing Python monorepo with shared dependencies |

### 📋 Reference Guides

| Document                                                         | Description                                              |
| ---------------------------------------------------------------- | -------------------------------------------------------- |
| **[State Marker System](state-marker-system.md)**                | 📋 Extraction progress tracking and recovery system      |
| **[State Marker Periodic Updates](state-marker-periodic-updates.md)** | 💾 Periodic state saves implementation and crash recovery |
| **[Emoji Guide](emoji-guide.md)**                                | 📋 Standardized emoji usage across the project           |
| **[Consumer Cancellation](consumer-cancellation.md)**       | 🔄 File completion and consumer lifecycle management     |
| **[File Completion Tracking](file-completion-tracking.md)** | 📊 Intelligent completion tracking and stalled detection |
| **[Platform Targeting](platform-targeting.md)**             | 🎯 Cross-platform compatibility guidelines               |
| **[Neo4j Indexing](neo4j-indexing.md)**                     | 🔗 Advanced Neo4j indexing strategies                    |
| **[Performance Benchmarks](performance-benchmarks.md)**     | 📈 Performance benchmarks and tuning results             |

## 🎯 Documentation by Role

### For New Users

Start here to get up and running quickly:

1. **[Quick Start Guide](quick-start.md)** - Get Discogsography running
1. **[Architecture Overview](architecture.md)** - Understand the system
1. **[Usage Examples](usage-examples.md)** - Try some queries
1. **[Configuration Guide](configuration.md)** - Customize settings

### For Developers

Get set up for development and understand our workflows:

1. **[Development Guide](development.md)** - Set up your dev environment
1. **[Contributing Guide](contributing.md)** - Learn how to contribute
1. **[Testing Guide](testing-guide.md)** - Write and run tests
1. **[Logging Guide](logging-guide.md)** - Follow logging standards
1. **[GitHub Actions Guide](github-actions-guide.md)** - Understand CI/CD

### For DevOps Engineers

Deploy and maintain Discogsography in production:

1. **[Docker Security](docker-security.md)** - Secure container practices
1. **[Dockerfile Standards](dockerfile-standards.md)** - Build optimization
1. **[Configuration Guide](configuration.md)** - Production settings
1. **[Monitoring Guide](monitoring.md)** - Observe and debug
1. **[Performance Guide](performance-guide.md)** - Optimize performance
1. **[Maintenance Guide](maintenance.md)** - Keep systems healthy

### For Data Engineers

Work with the music data and databases:

1. **[Database Schema](database-schema.md)** - Understand data structures
1. **[Usage Examples](usage-examples.md)** - Query the databases
1. **[Performance Guide](performance-guide.md)** - Optimize queries
1. **[Database Resilience](database-resilience.md)** - Connection patterns

### For Troubleshooting

When things go wrong:

1. **[Troubleshooting Guide](troubleshooting.md)** - Common issues and fixes
1. **[Monitoring Guide](monitoring.md)** - Debug and diagnose
1. **[Logging Guide](logging-guide.md)** - Configure logging and debug
1. **[Performance Guide](performance-guide.md)** - Performance issues

## 📝 Documentation Standards

When creating or updating documentation:

### File Naming

- Use **lowercase with hyphens**: `new-feature-guide.md`
- Be **descriptive**: `database-backup-procedures.md` not `db-backup.md`
- Avoid **abbreviations** unless widely known (e.g., `api`, `sql`)

### Structure

- **Header**: Title, description, and navigation links
- **Overview**: Brief introduction to the topic
- **Sections**: Organized with clear headings
- **Examples**: Practical code examples where applicable
- **Related Docs**: Links to related documentation
- **Last Updated**: Date at the bottom

### Content Guidelines

- **Clear and concise**: Get to the point quickly
- **Code examples**: Include working code snippets
- **Commands**: Show exact commands to run
- **Screenshots**: Use where helpful (but don't overdo it)
- **Emojis**: Follow the [Emoji Guide](emoji-guide.md)
- **Diagrams**: Use Mermaid for architecture and flow diagrams

### Mermaid Diagrams

- Use **consistent styling** across diagrams
- Include **meaningful colors** (see existing docs for palette)
- Keep diagrams **simple and focused**
- Add **alt text** for accessibility

### Example Header Format

```markdown
# 🔧 Document Title

<div align="center">

**Brief description of what this document covers**

[🏠 Back to Main](../README.md) | [📚 Documentation Index](README.md) | [Related Doc](related-doc.md)

</div>

## Overview

Brief introduction to the topic...
```

## 🤝 Contributing to Documentation

To add or improve documentation:

1. **Create or edit** a `.md` file in this directory
1. **Follow naming convention**: `lowercase-with-hyphens.md`
1. **Use the standard header** format shown above
1. **Add to this README** in the appropriate section
1. **Update main README.md** if it's a major guide
1. **Test all code examples** to ensure they work
1. **Check all links** are valid and point to the right place
1. **Run spell check** before committing

### Documentation Checklist

Before submitting documentation changes:

- [ ] File name follows convention (lowercase-with-hyphens)
- [ ] Header includes title, description, and navigation
- [ ] Overview section explains the purpose
- [ ] Code examples are tested and work
- [ ] All links are valid
- [ ] Emojis follow the emoji guide
- [ ] Mermaid diagrams render correctly
- [ ] "Last Updated" date is current
- [ ] Added to docs/README.md index
- [ ] Updated main README.md if needed
- [ ] Spell-checked and proofread

## 📊 Documentation Coverage

Current documentation covers:

- ✅ Getting started and quick setup
- ✅ Complete architecture documentation
- ✅ Configuration and environment variables
- ✅ Database schemas and usage examples
- ✅ Development environment setup
- ✅ Testing strategies and patterns
- ✅ CI/CD workflows and automation
- ✅ Docker and containerization
- ✅ Security best practices
- ✅ Performance optimization
- ✅ Monitoring and debugging
- ✅ Troubleshooting common issues
- ✅ Maintenance and operations
- ✅ Contributing guidelines

## 🔍 Finding Documentation

### Search Tips

**By Topic**:

- Architecture → [Architecture Overview](architecture.md)
- Installation → [Quick Start Guide](quick-start.md)
- Queries → [Usage Examples](usage-examples.md)
- Errors → [Troubleshooting Guide](troubleshooting.md)
- Performance → [Performance Guide](performance-guide.md)
- Development → [Development Guide](development.md)

**By Service**:

- Each service has its own README in the service directory
- See architecture docs for service interaction diagrams
- Check monitoring docs for service-specific debugging

**By Use Case**:

- Setting up for the first time → Quick Start
- Adding a feature → Development & Contributing
- Debugging an issue → Troubleshooting & Monitoring
- Deploying to production → Configuration & Security
- Optimizing performance → Performance & Database guides

## 💬 Getting Help

If you can't find what you're looking for:

1. **Search this index** - Use Cmd+F/Ctrl+F to search this page
1. **Check [CLAUDE.md](../CLAUDE.md)** - AI development guidance
1. **Read service READMEs** - Service-specific docs in each directory
1. **Browse [GitHub Discussions](https://github.com/SimplicityGuy/discogsography/discussions)** - Q&A and community help
1. **Create an issue** - [Report documentation gaps](https://github.com/SimplicityGuy/discogsography/issues/new)

## 📈 Documentation Metrics

Help us improve documentation:

- **Missing something?** [Create an issue](https://github.com/SimplicityGuy/discogsography/issues/new?labels=documentation)
- **Found a typo?** [Submit a PR](../CONTRIBUTING.md)
- **Have a question?** [Ask in Discussions](https://github.com/SimplicityGuy/discogsography/discussions/new?category=q-a)
- **Want to contribute?** See [Contributing Guide](contributing.md)

______________________________________________________________________

<div align="center">

**Last Updated**: 2026-02-12

Made with ❤️ by the Discogsography community

</div>
