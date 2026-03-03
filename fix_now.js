const fs = require('fs');
const glob = require('glob');
const path = require('path');

const files = glob.sync('src/**/*.py', { ignore: 'venv/**' });

files.forEach(file => {
    let content = fs.readFileSync(file, 'utf8');
    let changed = false;

    if (content.includes('server_default="now()"')) {
        content = content.replace(/server_default="now\(\)"/g, 'server_default=func.now()');
        
        // Ensure func is imported from sqlalchemy
        if (!content.includes('from sqlalchemy import') && !content.includes('import sqlalchemy')) {
             // Harder to fix automatically without knowing existing imports
        } else if (content.includes('from sqlalchemy import') && !content.includes('func')) {
             content = content.replace(/from sqlalchemy import (.*)/, 'from sqlalchemy import $1, func');
        }
        changed = true;
    }

    if (changed) {
        fs.writeFileSync(file, content);
        console.log('Fixed:', file);
    }
});
