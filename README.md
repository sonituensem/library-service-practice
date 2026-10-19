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

The implemented API endpoints and project commands are documented below.

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
| `POST` | `/api/users/` | Register with email, password, and optional first/last name | Public |
| `POST` | `/api/users/token/` | Obtain an access and refresh JWT using email and password | Public |
| `POST` | `/api/users/token/refresh/` | Obtain a new access JWT using a refresh token | Public |
| `GET` | `/api/users/me/` | Retrieve the authenticated user's profile | JWT |
| `PUT`, `PATCH` | `/api/users/me/` | Update email, password, first name, or last name | JWT |

Register with `POST /api/users/` and a JSON body containing `email` and
`password`. `first_name` and `last_name` are optional:

```json
{
  "email": "reader@example.com",
  "password": "StrongPass9#",
  "first_name": "Alex",
  "last_name": "Reader"
}
```

The response is `201 Created` with the user's `id`, `email`, `first_name`, and
`last_name`. To sign in, send `{"email": "reader@example.com", "password":
"StrongPass9#"}` to `POST /api/users/token/`; the response contains `access`
and `refresh` tokens. Send `{"refresh": "<refresh-token>"}` to
`POST /api/users/token/refresh/` to obtain a new `access` token.

Send the access token in the `Authorize` header using the `Bearer` scheme:

```http
Authorize: Bearer <access-token>
```

`GET /api/users/me/` returns the current user's profile. Send any of `email`,
`password`, `first_name`, or `last_name` in a JSON body to
`PUT /api/users/me/` or `PATCH /api/users/me/` to update it. Both update
methods accept omitted fields and return the updated profile. Duplicate emails
and weak passwords return `400 Bad Request` with field errors.

Passwords are validated with Django's configured password validators, stored
as hashes, and never returned by the API. The `is_staff` flag is never editable
through these endpoints.

## Books API

| Method | Endpoint | Purpose | Access |
| --- | --- | --- | --- |
| `GET` | `/api/books/` | List all books and their available inventory | Public |
| `POST` | `/api/books/` | Add a book | Staff JWT |
| `GET` | `/api/books/<id>/` | Retrieve one book | Public |
| `PUT`, `PATCH` | `/api/books/<id>/` | Replace or update a book, including its inventory | Staff JWT |
| `DELETE` | `/api/books/<id>/` | Delete a book | Staff JWT |

Use a JSON body for `POST` and `PUT`; `PATCH` accepts only the fields to change:

```json
{
  "title": "The Hobbit",
  "author": "J. R. R. Tolkien",
  "cover": "HARD",
  "inventory": 3,
  "daily_fee": "1.25"
}
```

`cover` accepts `HARD` or `SOFT`. `inventory` is a nonnegative integer: zero
means no copies are currently available. `daily_fee` is a nonnegative USD
decimal with two fractional digits. Responses include the book's generated
`id`. Invalid field values return `400 Bad Request`; an unknown book id returns
`404 Not Found`. Anyone can read the catalogue. Create, update, and delete
requests require a JWT for a staff user; anonymous and non-staff users receive
an authorization error for write requests.

## Borrowings API

| Method | Endpoint | Purpose | Access |
| --- | --- | --- | --- |
| `POST` | `/api/borrowings/` | Borrow an available book | JWT |
| `GET` | `/api/borrowings/` | List visible borrowing records | JWT |
| `GET` | `/api/borrowings/<id>/` | Retrieve one borrowing with its book details | JWT |
| `POST` | `/api/borrowings/<id>/return/` | Return a borrowed book | JWT |

Create a borrowing with `book_id` and `expected_return_date`:

```json
{
  "book_id": 1,
  "expected_return_date": "2026-11-01"
}
```

The server sets `borrow_date` to the current local date and assigns the
authenticated user. The client cannot set the borrower or actual return date.
If the book has no available copies, the request returns `400 Bad Request` and
does not create a borrowing. A successful request reserves one copy by
decrementing the book's `inventory`.

Return an active borrowing with an empty `POST` request to
`/api/borrowings/<id>/return/`. The server sets `actual_return_date` to the
current local date and restores one copy to the book's `inventory`. A borrowing
cannot be returned twice; a repeated request returns `400 Bad Request` without
changing the inventory. Customers can return only their own borrowings; staff
users can return any borrowing.

Customers see only their own borrowing records; staff users can see all records.
Each response includes the borrower id, borrowing dates, and a nested `book`
object with the book's current inventory information.

## API documentation

Interactive Swagger UI is available at `/api/docs/` and the OpenAPI schema at
`/api/schema/`. In Swagger UI, enter `Bearer <access-token>` in the `Authorize`
authentication field before trying protected operations.

## Tests and coverage

```shell
coverage run manage.py test
coverage report
```
