#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int  gcd(int  x,int  y, int num)
 { 
        int  t;
        if(x<y)         
		{
			t=x;                 
			x=y;                 
			y=t;         
		} 
        if(x%y==0)
			return  num+1;
		else
		{
            num++;
			return gcd(y,x%y,num);
        }
}
int bei(int x,int y,int num)
{
    int temp=x;
    while(temp%y)
    {
        num++;
        temp=temp+x;
    }
    return num;
}

int main()
{
    int m,n,x1,x2;
    scanf("%d%d",&m,&n);
    x1=gcd(m,n,0);
    if (m>n) x2=bei(m,n,0);
    else x2=bei(n,m,0);
    printf("%d %d\n",x1,x2);
}
