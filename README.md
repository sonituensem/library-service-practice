# Library Service

A Django REST Framework API for managing a library's books, customers, and borrowings.
This repository is the Flex practice project; no front-end is included.

## Project workflow

- Implement each selected task on its own clearly named branch.
- Commit small, complete changes throughout the task.
- Open a separate pull request to `main` for each coding task.
- Keep credentials and local configuration out of Git.

## Selected implementation scope

The planned tasks cover user registration and JWT authentication, book inventory,
book permissions, and the core borrowing lifecycle. Tests, Swagger documentation,
test coverage reporting, and a complete README are project-wide requirements.

The API setup and endpoint documentation will be added alongside the implementation.

## Local setup

```shell
python -m venv .venv
```

Activate the virtual environment, then install dependencies and prepare the database:

```shell
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

The API is available below `/api/`.

## Users API

| Method | Endpoint | Purpose | Access |
| --- | --- | --- | --- |
| `POST` | `/api/users/register/` | Register with email, password, and optional first/last name | Public |
| `POST` | `/api/users/token/` | Obtain an access and refresh JWT using email and password | Public |
| `POST` | `/api/users/token/refresh/` | Obtain a new access JWT using a refresh token | Public |
| `GET` | `/api/users/me/` | Retrieve the authenticated user's profile | JWT |
| `PUT`, `PATCH` | `/api/users/me/` | Update first or last name | JWT |

Send the access token in the `Authorize` header using the `Bearer` scheme:

```http
Authorize: Bearer <access-token>
```

Passwords are validated with Django's configured password validators, stored as hashes, and never returned by the API. A user can update their own first and last name; email is read-only after registration.

## Tests and coverage

```shell
coverage run manage.py test
coverage report
```
