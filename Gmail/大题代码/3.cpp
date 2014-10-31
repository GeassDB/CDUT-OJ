#include <iostream>
#include <cstdio>
#include <cstring>
using namespace std;

const int maxn = 110;
char field[maxn][maxn];
int dir[8][2] = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {-1, -1}, {1, -1}, {-1, 1}};
int m, n;
bool flag;
bool dfs(int x, int y);
int main()
{

    int ans;
	scanf("%d %d", &m ,&n);
	ans = 0;
	for(int i = 0; i < m; i++)
		scanf("%s", field[i]);
	for(int i = 0; i < m; i++)
	{
		for(int j = 0; j < n; j++)
		{
			flag = false;
			if(dfs(i, j))
				ans++;
		}
	}
	printf("%d\n", ans);

return 0;
}

bool dfs(int x, int y)
{
if(field[x][y] == '*')
	return flag;
flag = true;
field[x][y] = '*';
int tx, ty;
for(int i = 0; i < 8; i++)
{
	tx = x + dir[i][0]; ty = y + dir[i][1];
	if(tx >= 0 && tx < m && ty >= 0 && ty < n)
		dfs(tx, ty);
}
return flag;
}
