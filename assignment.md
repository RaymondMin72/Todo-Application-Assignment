# To-Do List Application — Technical Assignment

## Assignment Requirements

Our goal isn't just to see a working application, but to understand how you build quality software. We encourage you to use any tools, libraries, or frameworks you're comfortable with that help you achieve a clean, maintainable, and testable solution. This includes modern tools like Generative AI (e.g., GitHub Copilot, ChatGPT); we view these as tools that can enable faster software development.

However, the expectation for high-quality, well-structured, testable, and readable code remains unchanged regardless of the tools employed. The final submission should be consistent, coherent, and represent your understanding and ownership of the design and implementation.

Please approach this as you would a small, real-world feature implementation. If time gets in the way please look to reduce the feature scope instead of the quality of the submission.

## Scenario

Build a To-Do List Application.

## Objective

Create a to-do list application that allows users to manage their tasks.

## Core Requirements

### Programming Language

Please implement the solution in one of the following:

- JavaScript/TypeScript (Node.js)
- Python
- C#
- Java

### Interface — Choose One

Select the primary way a user interacts with your application.

Options include:

#### Command-Line Interface (CLI)

Accept commands and arguments to perform actions.

#### Basic Web Interface

Implement simple web pages/forms (minimal frontend JS/styling is fine) to interact with the backend logic.

Focus on functionality over visual polish.

Frameworks like NextJS, Flask/Django, ASP.NET Core MVC/Razor Pages or any other frameworks are acceptable.

#### SPA

Implement a solution using React, Vue, Angular, and/or any other modern SPA framework.

#### RESTful API

Design API endpoints, preferably returning JSON, that allow clients to manage to-do items.

> **Important Note:** Regardless of your choice, the primary evaluation focus remains on the architecture, testing, and code quality, not the sophistication or polish of the interface itself.

### Data Model

Each to-do item must include:

- `title`: **Required**. A short description of the task.
- `description`: **Optional**. A longer explanation.
- `dueDate`: **Optional**. A date indicating when the task should be completed. `YYYY-MM-DD` format is fine.
- `isCompleted`: A boolean flag. Defaults to `false`.
- `createdAt`: Timestamp when the item was created.

### Functionality — CRUD + Status

Provide capabilities to perform the following actions through your chosen interface:

- **Add**: Create a new to-do item.
- **List**: Display all to-do items, including essential details such as title, due date, and completion status.
- **View**: Show details of a specific to-do item by its ID.
- **Update**: Modify the title, description, or due date of an existing item by its ID.
- **Complete**: Mark a specific to-do item as completed by its ID.
- **Incomplete**: Mark a specific to-do item as not completed by its ID.
- **Delete**: Remove a to-do item by its ID.

#### API Specifics — If RESTful API Is Chosen

Define clear endpoints, for example using standard REST conventions such as:

- `POST /todos`
- `GET /todos`
- `GET /todos/{id}`
- `PUT /todos/{id}`
- `DELETE /todos/{id}`
- Potentially `PATCH` or specific actions for complete/incomplete

Use standard HTTP methods and status codes.

JSON request/response bodies are preferred.

### Persistence

Data should persist between application runs.

A simple file-based storage mechanism, such as JSON or CSV, is sufficient.

You do not need to implement a full database unless you prefer.

An in-memory store with clear separation allowing for a switch to persistent storage is also acceptable if file I/O pushes you significantly over the time estimate.

## Optional Enhancements — If Time Permits

These are not required, but can be ways to further showcase your skills:

- Implement filtering the list, for example:
  - completed
  - incomplete
  - overdue
- Implement sorting the list, for example:
  - by due date
  - by creation date
  - by title
- Add input validation, especially important for APIs or Web UIs.
- Containerize the application, for example using Docker.

## Submission

Please provide a link to a Git repository, for example GitHub or GitLab.

Include a `README.md` file in the root of the repository with:

- Clear instructions on how to build and run the application.
- Instructions on how to run the tests.
- A brief explanation of your design choices, particularly regarding backend architecture and testing strategy.
- Any assumptions you made.
- Optional notes on any trade-offs you made due to the time constraint.

Ensure your commit history is reasonably clean and reflects your development process.
