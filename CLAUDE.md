# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

pyRail is an async Python library that provides a wrapper for the iRail API (Belgian railway system). It's designed as a reusable package distributed via PyPI, focusing on clean async interfaces with comprehensive type safety.

## Development Commands

### Package Management
- Install dependencies: `poetry install`
- Add new dependency: `poetry add <package>`
- Add dev dependency: `poetry add --group dev <package>`

### Testing
- Run all tests: `poetry run pytest`
- Run single test: `poetry run pytest tests/test_irail.py::test_function_name`
- Run with coverage: `poetry run pytest --cov=pyrail`

### Code Quality
- Lint code: `poetry run ruff check .`
- Auto-fix linting issues: `poetry run ruff check . --fix`
- Type check: `poetry run mypy pyrail/`
- Format code: `poetry run ruff format .`

### Building and Publishing
- Build package: `poetry build`
- Check package: `poetry check`
- Test publish: `poetry publish --dry-run`

## Architecture

### Core Components

- **`pyrail/irail.py`**: Main API wrapper class with async HTTP client, rate limiting (3 req/sec), and ETag caching
- **`pyrail/models.py`**: Data models using dataclasses with Mashumaro for JSON serialization/deserialization
- **`pyrail/__init__.py`**: Package exports (main `iRail` class)

### API Endpoints Supported
- `stations`: List all railway stations
- `liveboard`: Departure/arrival boards for stations
- `connections`: Route planning between stations  
- `vehicle`: Train information and real-time status
- `composition`: Train car composition details
- `disturbances`: Network disruptions and alerts

### Key Features
- **Async-first design**: Built with aiohttp for non-blocking operations
- **Rate limiting**: Automatic 3 req/sec limiting with burst capacity
- **Enhanced ETag caching**: Stores both ETags and response data, returns cached data on 304 responses
- **Session management**: Supports both internal and external aiohttp sessions
- **Multi-language**: Supports EN, FR, DE, NL responses
- **Type safety**: Full mypy compliance with strict settings
- **Exception handling**: Custom exceptions for different error scenarios instead of returning None

### Data Flow
1. API requests → `iRail` class methods
2. HTTP requests → aiohttp with rate limiting
3. JSON responses → Mashumaro models
4. Typed dataclass objects returned to caller

## Configuration

### Tool Settings
- **mypy**: Strict type checking with comprehensive settings in `pyproject.toml`
- **ruff**: Line length 120, comprehensive linting rules including complexity, docstrings, imports
- **pytest**: Async testing with pytest-asyncio and mocking support

### Dependencies
- **Runtime**: Python 3.12+, aiohttp, mashumaro with orjson
- **Development**: pytest, pytest-mock, pytest-asyncio, ruff, mypy

## Exception Handling

### Custom Exceptions (v0.4.0+)
- **PyRailError**: Base exception with status_code attribute
- **RateLimitError**: 429 status, includes retry_after attribute
- **InvalidRequestError**: 4xx client errors
- **NotFoundError**: 404 resource not found
- **ServerError**: 5xx server errors

**Breaking Change**: Methods now raise exceptions instead of returning None for errors.

## Enhanced ETag Caching System

### Architecture
The caching system uses a `CacheEntry` dataclass that stores:
- **ETag**: The server-provided ETag for cache validation
- **Data**: The actual API response data
- **Timestamp**: When the entry was cached for expiration tracking

### Key Components
- **`response_cache`**: Dictionary mapping cache keys to `CacheEntry` objects
- **`_generate_cache_key()`**: Creates unique cache keys based on method + language + parameters
- **`_add_etag_header()`**: Adds If-None-Match headers for conditional requests
- **`_handle_response()`**: Returns cached data for 304 Not Modified responses

### Cache Management Methods
- **`clear_cache()`**: Remove all cached entries
- **`get_cache_stats()`**: Get statistics about cache state
- **`set_cache_max_age()`**: Configure cache expiration time
- **`invalidate_cache_for_method()`**: Remove entries for specific API methods
- **`_cleanup_expired_cache_entries()`**: Automatic cleanup of expired entries

### Cache Key Strategy
Cache keys are generated using SHA256 hash of method + language + sorted parameters, ensuring:
- Deterministic keys for identical requests
- Parameter order independence  
- Collision-resistant unique identification

### Testing
Comprehensive test coverage includes:
- Cache entry lifecycle (creation, expiration, cleanup)
- ETag workflow (200 → cache → 304 → return cached data)
- Cache key generation and uniqueness
- Cache statistics and management operations
- Expired entry cleanup and automatic cache maintenance

## Testing Patterns

Tests use pytest with async support and mocking. Key patterns:
- Mock aiohttp responses for API calls
- Test rate limiting behavior
- Verify ETag caching functionality
- Test error handling for HTTP errors
- Validate model serialization/deserialization

## Development Workflow

1. All changes require tests and type checking to pass
2. Code must pass ruff linting 
3. Use Poetry for dependency management
4. Follow existing async patterns and error handling
5. Maintain comprehensive type hints throughout