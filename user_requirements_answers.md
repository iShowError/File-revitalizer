# USER REQUIREMENTS & ANSWERS

## ANSWERED QUESTIONS

### QUESTION 1: Filesystem Access Method
**ANSWER**: Do it for both
- Support both mounted filesystems AND unmounted/corrupted devices
- Need to find solution for managing both scenarios
- Implementation approach to be determined

### QUESTION 2: User Technical Level  
**ANSWER**: Mixed audience
- Support both Linux system administrators and general users
- Need interface that works for different technical levels

### QUESTION 3: Recovery Workflow
**ANSWER**: Option B - Step-by-step guided
- User follows guided steps for mounting (if needed)
- System guides through analysis process
- Educational/guided approach preferred

## ADDITIONAL REQUIREMENTS

### EXISTING PAGES
- **home.html** and **dashboard.html** exist and should remain unchanged
- Keep current functionality as-is
- Static values can remain static for now
- Dynamic data implementation comes after models are defined

### DEVELOPMENT APPROACH
- Define all models first
- Then implement dynamic data
- Preserve existing page structure and content

### QUESTION 4: Dual Filesystem Support Implementation
**ANSWER**: Option C - Create detection logic that automatically determines which method to use
- Auto-detect if filesystem is mounted or unmounted
- Use appropriate tool based on detection

### QUESTION 5: Existing Pages Integration  
**ANSWER**: Use existing "Start recovery now" button on home page
- Implement authentication flow (login/registration required)
- Login: email + password with registration link
- Registration: FirstName, LastName, email, create password, confirm password
- Handle authentication logic and edge cases

### QUESTION 6: Step-by-Step Workflow Integration
**ANSWER**: Recovery wizard opens when "Start recovery now" is clicked
- Direct flow from home page button to wizard

### QUESTION 7: User Interface Flow
**ANSWER**: Home → "Start recovery now" button → Step-by-step recovery wizard
- Simple linear flow with authentication gate

## AUTHENTICATION REQUIREMENTS

### Login Page
- Email and password fields
- Link to registration page for new users
- Handle existing user validation
- Redirect logic after successful login

### Registration Page  
- First Name, Last Name fields
- Email field
- Create password, confirm password
- Handle new user registration
- Edge case handling (duplicate email, etc.)

### Authentication Flow Decision
- Need to determine: Show login first OR redirect to login when needed
- Handle authenticated vs non-authenticated user states

## FEATURE SCOPE

### Features to Temporarily Ignore
**ANSWER**: Ignore non-functional features during implementation
- AI diagnosis feature in home page
- Admin profile functionality  
- Search feature in dashboard
- Any other partially implemented features

### Implementation Approach
- Focus only on core BTRFS recovery functionality
- Leave existing UI elements as-is (static/non-functional)
- Don't modify or remove existing features
- Implement only authentication + recovery workflow

## STATUS
All requirements clarified. Ready for implementation!
