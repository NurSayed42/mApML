import requests

# Login
login = requests.post('http://localhost:8000/api/v1/auth/login',
    json={'email': 'test@example.com', 'password': 'test12345'})
token = login.json()['access_token']
print(f'Token obtained')

# Create task
task = requests.post('http://localhost:8000/api/v1/tasks',
    json={'instruction': 'Write a complete business plan for an AI-powered education platform'},
    headers={'Authorization': f'Bearer {token}'})

if task.status_code in [200, 202]:
    print('✅ Task created successfully!')
    print(f'Task ID: {task.json()[\"id\"]}')
    print(f'Status: {task.json()[\"status\"]}')
else:
    print(f'Error: {task.status_code} - {task.text}')
